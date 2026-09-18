"""Designer: Gaussian Process multi-output + Bayesian optimization (PRD §9).

Pemilik: Marshal (A). Ditulis ulang oleh Nico saat ambil alih (17 Sep) agar cepat (vektorisasi).

    python -m fp.designer --train --scope global --version gp-global-v1      # model dasar (A-06)
    python -m fp.designer --bench                                            # ukur propose n=3

    d = Designer.load("artifacts/models/gp-global-v1.joblib")
    cands = d.propose(specs, n=3, seed=42, exclude=known_df)   # DataFrame: formula + prediksi + P_*
    d2 = Designer().fit(X_df, Y_df, prev=d)                     # retrain live (warm start)

Semua keluaran berupa DataFrame dengan kolom:
  formula : GLYCERIN..PHENOXYETHANOL, AQUA, RPM, HMIN, TEMP
  predict : mu_*/sd_*, VISCOSITY_CP(_LO/_HI), PH(_LO/_HI), D50_UM(_LO/_HI), P_STABLE, COST_IDR_PER_KG, UNCERTAINTY
  p_specs : P_VISC, P_PH, P_D50, P_STABLE, DET_OK, P_TARGET  (+ reason pada propose/rank_pool)
"""

from __future__ import annotations

import argparse
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional, Union

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm
from sklearn.base import clone
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.preprocessing import StandardScaler

from fp.palette import FEATURES, INGREDIENTS, PROCESS

TARGETS = {"visc": "VISCOSITY_CP", "ph": "PH", "d50": "D50_UM", "stab": "STABILITY_INDEX"}
TARGET_COLUMNS = list(TARGETS.values())
FORMULA_COLUMNS = INGREDIENTS + ["AQUA"] + PROCESS
OUTPUT_COLUMNS = TARGET_COLUMNS + ["STABLE", "COST_IDR_PER_KG"]
PREDICT_COLUMNS = [
    "VISCOSITY_CP", "VISCOSITY_CP_LO", "VISCOSITY_CP_HI",
    "PH", "PH_LO", "PH_HI",
    "D50_UM", "D50_UM_LO", "D50_UM_HI",
    "P_STABLE", "COST_IDR_PER_KG", "UNCERTAINTY",
]
P_COLUMNS = ["P_VISC", "P_PH", "P_D50", "P_STABLE", "DET_OK", "P_TARGET"]

Z95 = 1.96
AQUA_MIN = 50.0
TOL = 1e-6
CHUNK = 4096
N_TOP = 50
N_PERTURB = 100
PERTURB_FRAC = 0.05
DIVERSITY_MIN = 0.6
EXCLUDE_EPS = 1e-6
EXPLORATION_P = 1e-4
EXPLORATION_WEIGHT = 0.1
STABLE_FLIP = 0.05

PathLike = Union[str, Path]


class BoundedLBFGS:
    """Optimizer hyperparameter GP dengan batas iterasi (bisa di-pickle, beda dengan closure)."""

    def __init__(self, maxiter: int):
        self.maxiter = int(maxiter)

    def __call__(self, obj_func, initial_theta, bounds):
        res = minimize(obj_func, initial_theta, method="L-BFGS-B", jac=True, bounds=bounds, options={"maxiter": self.maxiter})
        return res.x, res.fun


def default_kernel():
    return ConstantKernel(1.0) * Matern(length_scale=np.ones(len(FEATURES)), length_scale_bounds=(1e-2, 1e3), nu=2.5) + WhiteKernel(
        1e-2, (1e-6, 1e0)
    )


# ---------------------------------------------------------------- helper data


@lru_cache(maxsize=1)
def _palette_arrays() -> tuple[dict[str, tuple[float, float]], np.ndarray, float]:
    """(bounds bahan+proses, harga bahan per kg urut INGREDIENTS, harga AQUA) — dibaca sekali."""
    from fp import palette

    b = palette.bounds()
    df = palette.load_palette()
    prices = dict(zip(df["code"], df["price_idr_per_kg"].astype(float)))
    return b, np.array([prices.get(c, 0.0) for c in INGREDIENTS]), float(prices.get("AQUA", 0.0))


def as_frame(formulas: Any) -> pd.DataFrame:
    if isinstance(formulas, pd.DataFrame):
        return formulas.reset_index(drop=True)
    if isinstance(formulas, Mapping):
        return pd.DataFrame([dict(formulas)])
    if hasattr(formulas, "model_dump"):
        return pd.DataFrame([formulas.model_dump()])
    return pd.DataFrame([f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in formulas])


def formula_matrix(df: pd.DataFrame) -> np.ndarray:
    """Kolom INGREDIENTS + PROCESS (kolom hilang = 0)."""
    cols = [df[c].to_numpy(dtype=float) if c in df.columns else np.zeros(len(df)) for c in INGREDIENTS + PROCESS]
    return np.column_stack(cols)


def features(formulas: Any) -> np.ndarray:
    """14 fitur §8.1.1: 10 bahan, RPM, HMIN, TEMP, OIL_PHASE."""
    return _with_oil(formula_matrix(as_frame(formulas)))


def complete_frame(m: np.ndarray) -> pd.DataFrame:
    """Matriks INGREDIENTS+PROCESS -> DataFrame kolom formula dengan AQUA = 100 − Σ bahan."""
    df = pd.DataFrame(m, columns=INGREDIENTS + PROCESS)
    df["AQUA"] = np.round(100.0 - df[INGREDIENTS].sum(axis=1), 6)
    return df[FORMULA_COLUMNS]


def cost_vector(m: np.ndarray) -> np.ndarray:
    _, prices, aqua_price = _palette_arrays()
    ing = m[:, : len(INGREDIENTS)]
    aqua = 100.0 - ing.sum(axis=1)
    return np.round(ing @ prices / 100.0 + aqua * aqua_price / 100.0, 2)


def valid_vector(m: np.ndarray) -> np.ndarray:
    b, _, _ = _palette_arrays()
    ok = np.isfinite(m).all(axis=1)
    for j, c in enumerate(INGREDIENTS + PROCESS):
        lo, hi = b[c]
        ok &= (m[:, j] >= lo - TOL) & (m[:, j] <= hi + TOL)
    ok &= (100.0 - m[:, : len(INGREDIENTS)].sum(axis=1)) >= AQUA_MIN - TOL
    return ok


def specs_dict(specs: Any) -> dict[str, Any]:
    return specs.model_dump(mode="json") if hasattr(specs, "model_dump") else dict(specs)


def _bounds_arrays(niacinamide_min: float) -> tuple[np.ndarray, np.ndarray]:
    b, _, _ = _palette_arrays()
    cols = INGREDIENTS + PROCESS
    lo = np.array([b[c][0] for c in cols], dtype=float)
    hi = np.array([b[c][1] for c in cols], dtype=float)
    j = cols.index("NIACINAMIDE")
    lo[j] = min(max(lo[j], niacinamide_min), hi[j])
    return lo, hi


def sample_formulas(n: int, rng: np.random.RandomState, niacinamide_min: float = 0.0) -> np.ndarray:
    """n formula valid acak seragam (NIACINAMIDE di [min_spec, max]); tolak AQUA < 50."""
    lo, hi = _bounds_arrays(niacinamide_min)
    out, got = [], 0
    while got < n:
        batch = rng.uniform(lo, hi, size=(max(2 * (n - got), 64), len(lo)))
        batch = batch[100.0 - batch[:, : len(INGREDIENTS)].sum(axis=1) >= AQUA_MIN]
        out.append(batch)
        got += len(batch)
    return np.vstack(out)[:n]


def _perturb(m: np.ndarray, per_row: int, rng: np.random.RandomState, niacinamide_min: float) -> np.ndarray:
    lo, hi = _bounds_arrays(niacinamide_min)
    rep = np.repeat(m, per_row, axis=0)
    rep = np.clip(rep + rng.normal(0.0, 1.0, size=rep.shape) * (PERTURB_FRAC * (hi - lo)), lo, hi)
    return rep[100.0 - rep[:, : len(INGREDIENTS)].sum(axis=1) >= AQUA_MIN]


# ---------------------------------------------------------------- Designer


class Designer:
    is_stub = False

    def __init__(self, version: str = "gp-global-v1", scope: str = "global", seed: int = 42):
        self.version = version
        self.scope = scope
        self.seed = seed
        self.models: dict[str, GaussianProcessRegressor] = {}
        self.scaler: Optional[StandardScaler] = None
        self.train_X_scaled: Optional[np.ndarray] = None
        self.target_sd: dict[str, float] = {}
        self.n_train = 0
        self.parent_version: Optional[str] = None
        self.created_at: Optional[str] = None
        self.fit_seconds: Optional[float] = None
        self.fitted = False

    # ------------------------------------------------ training

    def fit(
        self,
        formulas: Any,
        outputs: Any = None,
        prev: Optional["Designer"] = None,
        n_restarts_optimizer: int = 2,
        maxiter: Optional[int] = None,
    ) -> "Designer":
        """Latih 4 GP. `outputs=None` -> kolom target diambil dari `formulas`. `prev` -> warm start kernel."""
        started = time.perf_counter()
        table = as_frame(formulas)
        out = table if outputs is None else as_frame(outputs)
        X = features(table)
        y_all = {name: _transform_target(name, out[col].to_numpy(dtype=float)) for name, col in TARGETS.items()}
        mask = np.isfinite(X).all(axis=1)
        for y in y_all.values():
            mask &= np.isfinite(y)
        X = X[mask]
        if len(X) < 3:
            raise ValueError(f"data training terlalu sedikit ({len(X)} baris valid)")

        self.scaler = StandardScaler().fit(X)
        Xs = self.scaler.transform(X)
        warm = prev is not None and bool(getattr(prev, "models", None))
        self.models, self.target_sd = {}, {}
        for name in TARGETS:
            y = y_all[name][mask]
            self.target_sd[name] = float(np.std(y)) or 1.0
            if warm and name in prev.models:
                # retrain live: pakai hyperparameter hasil optimasi versi sebelumnya (tambah 1 baris tidak
                # mengubahnya berarti; diukur selisih prediksi log10 visc ≤ 0,007). maxiter>0 -> optimasi terbatas.
                kernel = clone(prev.models[name].kernel_)
                optimizer: Any = BoundedLBFGS(maxiter) if maxiter else None
                restarts = 0
            else:
                kernel = default_kernel()
                optimizer = BoundedLBFGS(maxiter) if maxiter else "fmin_l_bfgs_b"
                restarts = n_restarts_optimizer
            gp = GaussianProcessRegressor(
                kernel=kernel, normalize_y=True, n_restarts_optimizer=restarts, optimizer=optimizer, random_state=self.seed
            )
            self.models[name] = gp.fit(Xs, y)
        self.train_X_scaled = Xs
        self.n_train = int(len(X))
        self.parent_version = getattr(prev, "version", None) if prev is not None else None
        from fp.config import now_iso

        self.created_at = now_iso()
        self.fit_seconds = round(time.perf_counter() - started, 3)
        self.fitted = True
        return self

    # ------------------------------------------------ prediksi

    def transform(self, formulas: Any) -> np.ndarray:
        self._require_fit()
        return self.scaler.transform(features(formulas))

    def predict(self, formulas: Any) -> pd.DataFrame:
        return self._predict_matrix(formula_matrix(as_frame(formulas)))

    def p_specs(self, formulas: Any, specs: Any) -> pd.DataFrame:
        m = formula_matrix(as_frame(formulas))
        return self._score(m, self._predict_matrix(m), specs_dict(specs))

    def propose(
        self,
        specs: Any,
        n: int = 3,
        seed: int = 42,
        exclude: Any = None,
        n_samples: int = 30000,
    ) -> pd.DataFrame:
        """n kandidat baru terurut (§9.5)."""
        self._require_fit()
        sp = specs_dict(specs)
        rng = np.random.RandomState(seed)
        nia_min = float(sp.get("NIACINAMIDE_MIN_PCT", 0.0) or 0.0)

        m = sample_formulas(int(n_samples), rng, nia_min)
        scored = self._score(m, self._predict_matrix(m), sp)
        top = np.argsort(-scored["P_TARGET"].to_numpy(), kind="stable")[: min(N_TOP, len(m))]
        m2 = _perturb(m[top], N_PERTURB, rng, nia_min)
        if len(m2):
            m = np.vstack([m, m2])
            scored = pd.concat([scored, self._score(m2, self._predict_matrix(m2), sp)], ignore_index=True)

        Z = self.scaler.transform(_with_oil(m))
        keep = np.ones(len(m), dtype=bool)
        if exclude is not None:
            ex = as_frame(exclude)
            if len(ex):
                keep &= _min_distance(Z, self.scaler.transform(features(ex))) >= EXCLUDE_EPS
        return self._select(scored, Z, keep, n)

    def rank_pool(self, pool: Any, specs: Any, n: int = 3) -> pd.DataFrame:
        """n baris pool terbaik dengan aturan diversity yang sama; hasil lab pool TIDAK ikut (anti bocor)."""
        self._require_fit()
        df = as_frame(pool)
        m = formula_matrix(df)
        scored = self._score(m, self._predict_matrix(m), specs_dict(specs))
        Z = self.scaler.transform(_with_oil(m))
        picked = self._select(scored, Z, np.ones(len(m), dtype=bool), n, return_index=True)
        meta_cols = [c for c in df.columns if c not in FORMULA_COLUMNS and c not in OUTPUT_COLUMNS and c != "variant"]
        meta = df.iloc[picked["_row"].to_numpy()][meta_cols].reset_index(drop=True)
        return pd.concat([meta, picked.drop(columns="_row")], axis=1)

    # ------------------------------------------------ simpan / muat

    def metadata(self) -> dict[str, Any]:
        import os

        return {
            "version": self.version,
            "scope": self.scope,
            "n_train": self.n_train,
            "created_at": self.created_at,
            "parent_version": self.parent_version,
            "seed": self.seed,
            "kernels": {k: str(v.kernel_) for k, v in self.models.items()},
            "instance": os.environ.get("INSTANCE"),
            "fit_seconds": self.fit_seconds,
        }

    def save(self, path: PathLike) -> Path:
        """joblib + metadata .json (atomik, R19)."""
        from fp.io_utils import write_joblib, write_json

        p = Path(path)
        write_joblib(p, self)
        write_json(p.with_suffix(".json"), self.metadata())
        return p

    @classmethod
    def load(cls, path: PathLike) -> "Designer":
        from fp.io_utils import load_joblib

        obj = load_joblib(path)
        if not isinstance(obj, cls):
            raise TypeError(f"{path} bukan Designer")
        defaults = cls().__dict__
        for k, v in defaults.items():
            obj.__dict__.setdefault(k, v)
        return obj

    # ------------------------------------------------ internal

    def _require_fit(self) -> None:
        if not self.fitted or self.scaler is None or not self.models:
            raise RuntimeError("Designer belum di-fit")

    def _predict_matrix(self, m: np.ndarray) -> pd.DataFrame:
        self._require_fit()
        Xs = self.scaler.transform(_with_oil(m))
        res: dict[str, np.ndarray] = {}
        rel = []
        for name, gp in self.models.items():
            mus, sds = [], []
            for start in range(0, len(Xs), CHUNK):
                mu, sd = gp.predict(Xs[start : start + CHUNK], return_std=True)
                mus.append(mu)
                sds.append(sd)
            mu = np.concatenate(mus) if mus else np.zeros(0)
            sd = np.maximum(np.concatenate(sds) if sds else np.zeros(0), 1e-9)
            res[f"mu_{name}"], res[f"sd_{name}"] = mu, sd
            rel.append(sd / (self.target_sd.get(name) or 1.0))
        out = pd.DataFrame(res)
        mv, sv = res["mu_visc"], res["sd_visc"]
        out["VISCOSITY_CP"] = 10**mv
        out["VISCOSITY_CP_LO"] = 10 ** (mv - Z95 * sv)
        out["VISCOSITY_CP_HI"] = 10 ** (mv + Z95 * sv)
        mp, spp = res["mu_ph"], res["sd_ph"]
        out["PH"], out["PH_LO"], out["PH_HI"] = mp, mp - Z95 * spp, mp + Z95 * spp
        md, sdd = res["mu_d50"], res["sd_d50"]
        out["D50_UM"], out["D50_UM_LO"], out["D50_UM_HI"] = np.exp(md), np.exp(md - Z95 * sdd), np.exp(md + Z95 * sdd)
        # Hasil uji STABLE dibalik dengan peluang 5% (noise uji, §8.1.2) yang tidak terlihat di STABILITY_INDEX
        # yang dilatih, jadi peluang hasil uji "stabil" = (1−f)·p + f·(1−p) (maks 0,95; temuan david-1935).
        p_index = norm.cdf(res["mu_stab"] / res["sd_stab"])
        out["P_STABLE"] = (1 - STABLE_FLIP) * p_index + STABLE_FLIP * (1 - p_index)
        out["COST_IDR_PER_KG"] = cost_vector(m)
        out["UNCERTAINTY"] = np.max(np.vstack(rel), axis=0)
        return out

    def _score(self, m: np.ndarray, pred: pd.DataFrame, sp: Mapping[str, Any]) -> pd.DataFrame:
        vmin, vmax = sp["VISCOSITY_CP"]
        pmin, pmax = sp["PH"]
        mu, sd = pred["mu_visc"].to_numpy(), pred["sd_visc"].to_numpy()
        p_visc = norm.cdf((np.log10(vmax) - mu) / sd) - norm.cdf((np.log10(vmin) - mu) / sd)
        mu, sd = pred["mu_ph"].to_numpy(), pred["sd_ph"].to_numpy()
        p_ph = norm.cdf((pmax - mu) / sd) - norm.cdf((pmin - mu) / sd)
        mu, sd = pred["mu_d50"].to_numpy(), pred["sd_d50"].to_numpy()
        p_d50 = norm.cdf((np.log(sp["D50_UM_MAX"]) - mu) / sd)
        p_stable = pred["P_STABLE"].to_numpy() if sp.get("STABLE", True) else np.ones(len(m))
        nia = m[:, INGREDIENTS.index("NIACINAMIDE")]
        det = (
            valid_vector(m)
            & (nia >= float(sp.get("NIACINAMIDE_MIN_PCT", 0.0) or 0.0) - TOL)
            & (pred["COST_IDR_PER_KG"].to_numpy() <= float(sp.get("COST_IDR_PER_KG_MAX", np.inf)) + TOL)
        ).astype(float)
        out = pd.concat([complete_frame(m), pred], axis=1)
        out["P_VISC"] = np.clip(p_visc, 0, 1)
        out["P_PH"] = np.clip(p_ph, 0, 1)
        out["P_D50"] = np.clip(p_d50, 0, 1)
        out["DET_OK"] = det
        out["P_TARGET"] = np.clip(out["P_VISC"] * out["P_PH"] * out["P_D50"] * p_stable * det, 0, 1)
        return out

    def _select(self, scored: pd.DataFrame, Z: np.ndarray, keep: np.ndarray, n: int, return_index: bool = False) -> pd.DataFrame:
        p = scored["P_TARGET"].to_numpy()
        exploration = bool(keep.any()) and not bool((p[keep] >= EXPLORATION_P).any())
        key = p + EXPLORATION_WEIGHT * scored["UNCERTAINTY"].to_numpy() if exploration else p.copy()
        key = np.where(keep, key, -np.inf)

        cost = scored["COST_IDR_PER_KG"].to_numpy()
        uncertainty = scored["UNCERTAINTY"].to_numpy()
        nia = scored["NIACINAMIDE"].to_numpy()
        visc = scored["VISCOSITY_CP"].to_numpy()
        d50 = scored["D50_UM"].to_numpy()

        valid_indices = [int(i) for i in np.flatnonzero(keep)]
        if not valid_indices:
            out = scored.iloc[[]].copy()
            if return_index:
                out["_row"] = []
            return out

        order = sorted(
            valid_indices,
            key=lambda i: (-round(float(key[i]), 4), float(cost[i]), float(uncertainty[i]), i),
        )

        best_p = float(np.max(key[valid_indices])) if valid_indices else 0.0

        chosen: list[int] = []
        # Multi-objective strategic curation across Pareto archetypes
        if best_p > 0.05 and len(valid_indices) >= n and not exploration:
            chosen.append(order[0])
            viable = [i for i in valid_indices if key[i] >= max(0.05, best_p * 0.4)]

            def _get_diverse_candidate(pool: list[int], sort_key, reverse=False):
                for i in sorted(pool, key=sort_key, reverse=reverse):
                    if i in chosen:
                        continue
                    if np.min(np.linalg.norm(Z[chosen] - Z[i], axis=1)) >= DIVERSITY_MIN:
                        return i
                for i in sorted(pool, key=sort_key, reverse=reverse):
                    if i not in chosen:
                        return i
                return None

            # Slot 2: High Active Efficacy (Niacinamide focus)
            if len(chosen) < n:
                cand2 = _get_diverse_candidate(viable, lambda i: (nia[i], key[i]), reverse=True)
                if cand2 is not None:
                    chosen.append(cand2)

            # Slot 3: Lean Cost Efficiency (Cost focus)
            if len(chosen) < n:
                cand3 = _get_diverse_candidate(viable, lambda i: (cost[i], -key[i]), reverse=False)
                if cand3 is not None:
                    chosen.append(cand3)

            # Slot 4: Rich Gel Texture (Viscosity focus)
            if len(chosen) < n:
                cand4 = _get_diverse_candidate(viable, lambda i: (visc[i], key[i]), reverse=True)
                if cand4 is not None:
                    chosen.append(cand4)

            # Slot 5: Micro-Emulsion (Fine droplet D50 focus)
            if len(chosen) < n:
                cand5 = _get_diverse_candidate(viable, lambda i: (d50[i], -key[i]), reverse=False)
                if cand5 is not None:
                    chosen.append(cand5)

        # Fallback to standard diverse greedy selection if slots remain unfilled
        if len(chosen) < n:
            for i in order:
                if len(chosen) >= n:
                    break
                if i in chosen:
                    continue
                if chosen and np.min(np.linalg.norm(Z[chosen] - Z[i], axis=1)) < DIVERSITY_MIN:
                    continue
                chosen.append(i)

        if len(chosen) < n:
            taken = set(chosen)
            chosen += [i for i in order if i not in taken][: n - len(chosen)]

        out = scored.iloc[chosen].reset_index(drop=True)
        out["reason"] = "exploration" if exploration else None
        if return_index:
            out["_row"] = chosen
        return out


def _transform_target(name: str, y: np.ndarray) -> np.ndarray:
    if name == "visc":
        return np.log10(np.clip(y, 1e-3, None))
    if name == "d50":
        return np.log(np.clip(y, 1e-3, None))
    if name == "stab":
        c = np.clip(y, 0.01, 0.99)
        return np.log(c / (1 - c))
    return y


def _with_oil(m: np.ndarray) -> np.ndarray:
    j = {c: i for i, c in enumerate(INGREDIENTS)}
    oil = m[:, j["CCT"]] + m[:, j["DIMETHICONE"]] + 0.5 * m[:, j["CETEARYL_ALCOHOL"]]
    return np.column_stack([m, oil])


def _min_distance(Z: np.ndarray, E: np.ndarray) -> np.ndarray:
    """Jarak Euclidean terkecil tiap baris Z ke himpunan E (dipotong agar hemat memori)."""
    out = np.full(len(Z), np.inf)
    zz = (Z**2).sum(axis=1)
    for start in range(0, len(E), 256):
        e = E[start : start + 256]
        d2 = zz[:, None] - 2 * Z @ e.T + (e**2).sum(axis=1)[None, :]
        out = np.minimum(out, np.sqrt(np.maximum(d2, 0)).min(axis=1))
    return out


# ---------------------------------------------------------------- CLI


def _load_historical(variant: str) -> pd.DataFrame:
    from fp.config import get_settings

    return pd.read_csv(get_settings().historical_csv(variant))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fp.designer")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--scope", default="global")
    parser.add_argument("--version", default="gp-global-v1")
    parser.add_argument("--variant", default="v1")
    parser.add_argument("--restarts", type=int, default=2)
    parser.add_argument("--out", default=None, help="folder model (default artifacts/models)")
    parser.add_argument("--bench", action="store_true", help="ukur propose n=3 dan retrain warm start")
    args = parser.parse_args(argv)
    if not (args.train or args.bench):
        parser.print_help()
        return 2
    import json

    from fp.config import get_settings

    # `python -m fp.designer` menjalankan file ini sebagai __main__; pakai class dari modul fp.designer
    # agar pickle menyimpan "fp.designer.Designer" (bukan "__main__.Designer" yang gagal dimuat backend).
    from fp.designer import Designer

    settings = get_settings()
    path = Path(args.out or settings.base_models_dir) / f"{args.version}.joblib"
    if args.train:
        hist = _load_historical(args.variant)
        t = time.perf_counter()
        d = Designer(version=args.version, scope=args.scope).fit(hist, n_restarts_optimizer=args.restarts)
        d.save(path)
        print(f"designer: {args.version} n_train={d.n_train} fit {time.perf_counter() - t:.1f} dtk -> {path}")
        for k, v in d.metadata()["kernels"].items():
            print(f"  {k}: {v}")
    if args.bench:
        d = Designer.load(path)
        specs = json.load(open(settings.briefs_json))[0]["specs"]
        t = time.perf_counter()
        c = d.propose(specs, n=3, seed=42)
        print(f"propose n=3 n_samples=30000: {time.perf_counter() - t:.2f} dtk; P_TARGET={c['P_TARGET'].round(3).tolist()}")
        hist = _load_historical(args.variant)
        t = time.perf_counter()
        d2 = Designer(version="bench").fit(pd.concat([hist, hist.head(1)], ignore_index=True), prev=d, n_restarts_optimizer=0)
        print(f"retrain warm start ({d2.n_train} baris): {time.perf_counter() - t:.2f} dtk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
