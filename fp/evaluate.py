"""Evaluasi dan bukti (PRD §10) -> artifacts/evaluation.json + artifacts/figures/*.png.

Pemilik: Marshal (A); ditulis Nico saat ambil alih. Wajib lewat antrean:
    bash scripts/heavy.sh bash scripts/evaluate.sh            # --all (20 seed, 3 varian)
    bash scripts/heavy.sh bash scripts/evaluate.sh quick      # --quick (5 seed, v1)

Semua angka UI/deck dibaca dari evaluation.json (R11). Semua hasil Virtual Lab = simulasi.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

BRIEF_ID = "niacinamide_gel_cream"
VARIANTS = ("v1", "v2", "v3")
STRATEGIES = ("ai", "random", "heuristic")
LAB_OUTPUT_KEYS = ("VISCOSITY_CP", "PH", "D50_UM", "STABILITY_INDEX", "STABLE", "COST_IDR_PER_KG")

MAX_BATCHES = 40
START_KNOWN = 10
REPLAY_MAX_STEPS = 80
LIPO_MAX_STEPS = 60
LIPO_START = 5
FULL_SEEDS = 20
QUICK_SEEDS = 5
HIT_RATE_SAMPLES = 2000
DEFAULT_JOBS = 8


# ---------------------------------------------------------------- data


def _settings():
    from fp.config import get_settings

    return get_settings()


def load_specs(brief_id: str = BRIEF_ID) -> dict[str, Any]:
    from fp.io_utils import read_json

    for b in read_json(_settings().briefs_json):
        if b["brief_id"] == brief_id:
            return dict(b["specs"])
    raise KeyError(f"brief {brief_id} tidak ada")


def load_historical(variant: str) -> pd.DataFrame:
    return pd.read_csv(_settings().historical_csv(variant))


def load_business() -> dict[str, float]:
    df = pd.read_csv(_settings().business_csv)
    return {str(r.key): float(r.value) for r in df.itertuples(index=False)}


def _limit_threads() -> None:
    try:
        from threadpoolctl import threadpool_limits

        threadpool_limits(1)
    except Exception:
        pass


# ---------------------------------------------------------------- 10.1 CV


def cross_validate(hist: pd.DataFrame, n_splits: int = 5, seed: int = 42) -> tuple[dict[str, Any], float, pd.DataFrame]:
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import KFold

    from fp.designer import Designer

    preds = []
    for tr, te in KFold(n_splits, shuffle=True, random_state=seed).split(hist):
        p = Designer(version="cv", seed=seed).fit(hist.iloc[tr], n_restarts_optimizer=0).predict(hist.iloc[te])
        p.index = hist.index[te]
        preds.append(p)
    p = pd.concat(preds).sort_index()
    y = hist.loc[p.index]

    yv, pv = np.log10(y["VISCOSITY_CP"].to_numpy()), p["mu_visc"].to_numpy()
    yp, pp = y["PH"].to_numpy(), p["PH"].to_numpy()
    yd, pd50 = np.log(y["D50_UM"].to_numpy()), p["mu_d50"].to_numpy()
    stable = y["STABLE"].astype(int).to_numpy()
    p_stable = p["P_STABLE"].to_numpy()

    def cover(col: str, actual: np.ndarray) -> float:
        return float(np.mean((p[f"{col}_LO"].to_numpy() <= actual) & (actual <= p[f"{col}_HI"].to_numpy())))

    cv = {
        "n": int(len(y)),
        "folds": n_splits,
        "visc": {
            "r2": _r2(yv, pv),
            "mae_log10": float(np.mean(np.abs(yv - pv))),
            "median_abs_cp": float(np.median(np.abs(y["VISCOSITY_CP"].to_numpy() - p["VISCOSITY_CP"].to_numpy()))),
            "baseline_r2": 0.0,
            "coverage95": cover("VISCOSITY_CP", y["VISCOSITY_CP"].to_numpy()),
        },
        "ph": {"r2": _r2(yp, pp), "mae": float(np.mean(np.abs(yp - pp))), "baseline_r2": 0.0, "coverage95": cover("PH", yp)},
        "d50": {
            "r2": _r2(yd, pd50),
            "mae_um": float(np.mean(np.abs(y["D50_UM"].to_numpy() - p["D50_UM"].to_numpy()))),
            "baseline_r2": 0.0,
            "coverage95": cover("D50_UM", y["D50_UM"].to_numpy()),
        },
        "stab": {
            "auc": float(roc_auc_score(stable, p_stable)) if 0 < stable.sum() < len(stable) else None,
            "brier": float(np.mean((p_stable - stable) ** 2)),
            "baseline_brier": float(np.mean((stable.mean() - stable) ** 2)),
        },
    }
    unc_max = float(np.percentile(p["UNCERTAINTY"], 80))
    parity = pd.DataFrame(
        {
            "visc_actual": yv, "visc_pred": pv, "ph_actual": yp, "ph_pred": pp,
            "d50_actual": yd, "d50_pred": pd50, "stab_actual": stable, "stab_pred": p_stable,
        }
    )
    return cv, unc_max, parity


def hit_rate_random(variant: str, specs: dict[str, Any], n: int = HIT_RATE_SAMPLES, seed: int = 20260917) -> float:
    from fp.designer import complete_frame, sample_formulas
    from fp.palette import meets_specs
    from fp.virtual_lab import VirtualLab

    rng = np.random.RandomState(seed)
    frame = complete_frame(sample_formulas(n, rng, 0.0))
    lab = VirtualLab(variant, seed=seed)
    hits = 0
    for i, f in enumerate(frame.to_dict("records")):
        hits += bool(meets_specs(f, lab.run_batch(f, seed_override=seed + i), specs)["ALL"])
    return hits / n


# ---------------------------------------------------------------- 10.3 Skenario A


def closed_loop_job(variant: str, seed: int, specs: dict[str, Any], max_batches: int, n_samples: int) -> tuple[str, int, dict[str, Optional[int]]]:
    _limit_threads()
    from fp import strategies as st
    from fp.palette import meets_specs
    from fp.virtual_lab import VirtualLab

    init = st.select_initial(load_historical(variant), specs, START_KNOWN, seed)
    result: dict[str, Optional[int]] = {}
    for strategy in STRATEGIES:
        rng = np.random.RandomState(100_000 + seed)
        lab = VirtualLab(variant, seed=seed)
        known = init.copy()
        result[strategy] = None
        for batch in range(1, max_batches + 1):
            f = st.choose(strategy, known, specs, seed * 1000 + batch, rng, n_samples)
            out = lab.run_batch(f, seed_override=seed * 1000 + batch)
            row = {**f, **{k: float(out[k]) for k in LAB_OUTPUT_KEYS}}
            known = pd.concat([known, pd.DataFrame([row])], ignore_index=True)
            if meets_specs(f, out, specs)["ALL"]:
                result[strategy] = batch
                break
    return variant, seed, result


# ---------------------------------------------------------------- 10.4 Skenario B


def replay_job(seed: int, specs: dict[str, Any], max_steps: int) -> tuple[int, dict[str, Optional[int]]]:
    _limit_threads()
    from sklearn.preprocessing import StandardScaler

    from fp import strategies as st
    from fp.designer import Designer, features

    pool = load_historical("v1").reset_index(drop=True)
    hits = dict(zip(pool["record_id"], st.hit_mask(pool, specs)))
    init = st.select_initial(pool, specs, START_KNOWN, seed)
    scaler = StandardScaler().fit(features(pool))
    result: dict[str, Optional[int]] = {}
    for strategy in STRATEGIES:
        rng = np.random.RandomState(200_000 + seed)
        known = init.copy()
        remaining = pool[~pool["record_id"].isin(known["record_id"])].reset_index(drop=True)
        result[strategy] = None
        for step in range(1, max_steps + 1):
            if remaining.empty:
                break
            if strategy == "ai":
                d = Designer(version="eval", seed=seed).fit(known, n_restarts_optimizer=0, maxiter=st.AI_MAXITER)
                rid = d.rank_pool(remaining, specs, n=1)["record_id"].iloc[0]
                idx = int(np.flatnonzero(remaining["record_id"].to_numpy() == rid)[0])
            elif strategy == "random":
                idx = int(rng.randint(len(remaining)))
            else:
                idx = st.nearest_row(remaining, st.choose_heuristic(known, specs, rng), scaler)
            row = remaining.iloc[[idx]]
            known = pd.concat([known, row], ignore_index=True)
            remaining = remaining.drop(index=remaining.index[idx]).reset_index(drop=True)
            if hits[row["record_id"].iloc[0]]:
                result[strategy] = step
                break
    return seed, result


# ---------------------------------------------------------------- 10.5 Skenario C


def liposome_job(seed: int, max_steps: int) -> tuple[int, dict[str, Optional[int]]]:
    _limit_threads()
    from fp import validation_liposome as vl

    df = vl.load_clean()
    return seed, {s: vl.replay_seed(df, seed, s, max_steps=max_steps, start_known=LIPO_START) for s in ("ai", "random")}


# ---------------------------------------------------------------- agregasi


def summarize(values: Iterable[Optional[int]], max_steps: int) -> dict[str, Any]:
    vals = list(values)
    if not vals:
        return {"median": None, "iqr": [None, None], "found_rate": None, "n_found": 0, "n_seeds": 0}
    filled = np.array([v if v is not None else max_steps + 1 for v in vals], dtype=float)
    return {
        "median": float(np.median(filled)),
        "iqr": [float(np.percentile(filled, 25)), float(np.percentile(filled, 75))],
        "found_rate": float(np.mean([v is not None for v in vals])),
        "n_found": int(sum(v is not None for v in vals)),
        "n_seeds": len(vals),
    }


def curve(per_strategy: dict[str, list[Optional[int]]], max_steps: int) -> list[dict[str, Any]]:
    out = []
    for b in range(1, max_steps + 1):
        point: dict[str, Any] = {"batch": b}
        for s, vals in per_strategy.items():
            point[s] = float(np.mean([v is not None and v <= b for v in vals])) if vals else None
        out.append(point)
    return out


# ---------------------------------------------------------------- figur


def make_figures(report: dict[str, Any], parity: Optional[pd.DataFrame], figdir: Path) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from fp.io_utils import write_figure

    figdir.mkdir(parents=True, exist_ok=True)
    made: list[str] = []
    colors = {"ai": "#2563eb", "random": "#9ca3af", "heuristic": "#f59e0b"}
    labels = {"ai": "AI (FormulaPilot)", "random": "Acak", "heuristic": "Heuristik formulator"}

    def save(fig, name):
        fig.tight_layout()
        write_figure(figdir / name, fig, dpi=150)
        plt.close(fig)
        made.append(name)

    def curve_plot(points, strategies, xlabel, title, name):
        fig, ax = plt.subplots(figsize=(6.4, 4))
        for s in strategies:
            ax.plot([p["batch"] for p in points], [p[s] for p in points], label=labels[s], color=colors[s], lw=2)
        ax.set(xlabel=xlabel, ylabel="Fraksi seed yang sudah menemukan hit", title=title)
        ax.set_ylim(0, 1.02)
        ax.legend()
        save(fig, name)

    cl = report["closed_loop"]["results"]
    if cl.get("v1", {}).get("curve"):
        curve_plot(cl["v1"]["curve"], STRATEGIES, "Batch uji Virtual Lab", "Closed-loop Virtual Lab v1 (simulasi)", "closed_loop_v1.png")

    variants = [v for v in VARIANTS if cl.get(v, {}).get("ai")]
    if variants:
        fig, ax = plt.subplots(figsize=(6.4, 4))
        w, x = 0.26, np.arange(len(variants))
        for i, s in enumerate(STRATEGIES):
            ax.bar(x + (i - 1) * w, [cl[v][s]["median"] for v in variants], w, label=labels[s], color=colors[s])
        ax.set_xticks(x, variants)
        ax.set(ylabel=f"Median batch sampai lolos (tidak ketemu = {report['closed_loop']['max_batches'] + 1})", title="Ketahanan terhadap varian simulator (simulasi)")
        ax.legend()
        save(fig, "closed_loop_variants.png")

    if report["replay_historical"].get("curve"):
        curve_plot(report["replay_historical"]["curve"], STRATEGIES, "Langkah (baris historis diungkap)", "Replay data historis v1 (simulasi)", "replay_historical.png")

    if report["liposome_validation"].get("curve"):
        curve_plot(report["liposome_validation"]["curve"], ("ai", "random"), "Langkah", "Validasi metode: data liposom nyata (non-skincare)", "liposome_validation.png")

    if parity is not None and len(parity):
        fig, axes = plt.subplots(2, 2, figsize=(7.2, 6.4))
        panels = [("visc", "log10 viskositas (cP)"), ("ph", "pH"), ("d50", "ln D50 (µm)"), ("stab", "P(stabil) vs stabil aktual")]
        for ax, (k, title) in zip(axes.ravel(), panels):
            a, p = parity[f"{k}_actual"].to_numpy(), parity[f"{k}_pred"].to_numpy()
            if k == "stab":
                ax.scatter(a + np.random.RandomState(0).uniform(-0.08, 0.08, len(a)), p, s=8, alpha=0.5, color="#2563eb")
                ax.set_xticks([0, 1], ["tidak stabil", "stabil"])
            else:
                ax.scatter(a, p, s=8, alpha=0.5, color="#2563eb")
                lo, hi = float(min(a.min(), p.min())), float(max(a.max(), p.max()))
                ax.plot([lo, hi], [lo, hi], color="#6b7280", lw=1)
            ax.set_title(title, fontsize=10)
        fig.suptitle("CV 5-fold: prediksi vs aktual (data historis simulasi v1)", fontsize=11)
        save(fig, "cv_parity.png")
    return made


# ---------------------------------------------------------------- orkestrasi


def run(
    quick: bool = False,
    out: Optional[Path] = None,
    figdir: Optional[Path] = None,
    jobs: int = DEFAULT_JOBS,
    seeds: Optional[int] = None,
    variants: Optional[Iterable[str]] = None,
    max_batches: int = MAX_BATCHES,
    replay_steps: int = REPLAY_MAX_STEPS,
    lipo_steps: int = LIPO_MAX_STEPS,
    n_samples: int = 5000,
    cv_rows: Optional[int] = None,
    hit_rate_samples: int = HIT_RATE_SAMPLES,
    brief_id: str = BRIEF_ID,
) -> dict[str, Any]:
    from joblib import Parallel, delayed

    from fp import strategies as st
    from fp import validation_liposome as vl
    from fp.config import now_iso
    from fp.io_utils import write_json
    from fp.schemas import EvaluationReport

    started = time.perf_counter()
    s = _settings()
    out = Path(out or s.evaluation_json)
    figdir = Path(figdir or s.figures_dir)
    seeds = seeds or (QUICK_SEEDS if quick else FULL_SEEDS)
    variants = tuple(variants or (("v1",) if quick else VARIANTS))
    specs = load_specs(brief_id)
    notes: list[str] = [
        "Semua skenario Virtual Lab adalah simulasi; bukan hasil lab nyata.",
        f"CV memakai n_restarts_optimizer=0 per fold; strategi ai melatih ulang GP tiap batch (maxiter {st.AI_MAXITER}), propose n_samples={n_samples}.",
    ]
    if quick:
        notes.append(f"quick: {seeds} seed, varian {list(variants)}")
    pool = Parallel(n_jobs=jobs, backend="loky") if jobs > 1 else None

    def parallel(calls):
        calls = list(calls)
        return pool(calls) if pool is not None else [fn(*a, **kw) for fn, a, kw in calls]

    t = time.perf_counter()
    hist_v1 = load_historical("v1")
    cv, unc_max, parity = cross_validate(hist_v1.head(cv_rows) if cv_rows else hist_v1)
    print(f"evaluate: CV {time.perf_counter() - t:.1f} dtk", flush=True)

    t = time.perf_counter()
    hit_rates: dict[str, Optional[float]] = {v: None for v in VARIANTS}
    for v in variants:
        hit_rates[v] = hit_rate_random(v, specs, n=hit_rate_samples)
    print(f"evaluate: hit rate acak {hit_rates} ({time.perf_counter() - t:.1f} dtk)", flush=True)

    t = time.perf_counter()
    a_raw = parallel(delayed(closed_loop_job)(v, sd, specs, max_batches, n_samples) for v in variants for sd in range(seeds))
    results: dict[str, Any] = {v: {} for v in VARIANTS}
    for v in variants:
        per = {k: [r[k] for vv, _, r in a_raw if vv == v] for k in STRATEGIES}
        results[v] = {k: summarize(per[k], max_batches) for k in STRATEGIES}
        results[v]["curve"] = curve(per, max_batches)
    print(f"evaluate: skenario A {time.perf_counter() - t:.1f} dtk", flush=True)

    t = time.perf_counter()
    b_raw = parallel(delayed(replay_job)(sd, specs, replay_steps) for sd in range(seeds))
    per_b = {k: [r[k] for _, r in b_raw] for k in STRATEGIES}
    replay_historical: dict[str, Any] = {
        "max_steps": replay_steps,
        "seeds": seeds,
        "start_known": START_KNOWN,
        "pool": int(len(hist_v1)),
        "pool_hits": int(st.hit_mask(hist_v1, specs).sum()),
        **{k: summarize(per_b[k], replay_steps) for k in STRATEGIES},
        "curve": curve(per_b, replay_steps),
    }
    print(f"evaluate: skenario B {time.perf_counter() - t:.1f} dtk", flush=True)

    t = time.perf_counter()
    liposome: dict[str, Any] = {
        "label": vl.LABEL,
        "rows": None,
        "hits": None,
        "source": vl.URL,
        "license": vl.LICENSE,
        "target": {"size_min": vl.SIZE_MIN, "size_max": vl.SIZE_MAX, "pdi_max": vl.PDI_MAX},
        "cv": {"size_nm_mae": None, "pdi_mae": None, "log_size_r2": None, "log_pdi_r2": None},
        "replay": {"ai": {"median": None, "found_rate": None}, "random": {"median": None, "found_rate": None}},
        "max_steps": lipo_steps,
        "seeds": seeds,
        "start_known": LIPO_START,
    }
    try:
        ldf = vl.load_clean()
        liposome.update(rows=int(len(ldf)), hits=int(ldf["HIT"].sum()), cv=vl.cross_validate(ldf))
        c_raw = parallel(delayed(liposome_job)(sd, lipo_steps) for sd in range(seeds))
        per_c = {k: [r[k] for _, r in c_raw] for k in ("ai", "random")}
        liposome["replay"] = {k: summarize(per_c[k], lipo_steps) for k in ("ai", "random")}
        liposome["curve"] = curve(per_c, lipo_steps)
    except FileNotFoundError as exc:
        notes.append(f"liposome_validation dilewati: {exc}")
    print(f"evaluate: skenario C {time.perf_counter() - t:.1f} dtk", flush=True)

    business = load_business()
    savings: dict[str, Any] = {
        "label": "simulasi",
        "batches_saved": None,
        "cost_saved_idr": None,
        "days_saved": None,
        "assumptions": {"cost_per_batch_idr": business.get("cost_per_batch_idr"), "days_per_batch": business.get("days_per_batch")},
        "basis": "skenario A varian v1: median batch random − median batch ai",
    }
    if results.get("v1", {}).get("ai"):
        saved = results["v1"]["random"]["median"] - results["v1"]["ai"]["median"]
        savings.update(
            batches_saved=saved,
            cost_saved_idr=saved * business.get("cost_per_batch_idr", 0.0),
            days_saved=saved * business.get("days_per_batch", 0.0),
        )
        if saved <= 0:
            notes.append("batches_saved ≤ 0: tidak ada klaim penghematan.")

    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "quick": bool(quick),
        "brief_id": brief_id,
        "specs": specs,
        "cv": cv,
        "unc_max": unc_max,
        "hit_rate_random": hit_rates,
        "closed_loop": {"max_batches": max_batches, "seeds": seeds, "start_known": START_KNOWN, "variants": list(variants), "results": results},
        "replay_historical": replay_historical,
        "liposome_validation": liposome,
        "savings_estimate": savings,
        "runtime_seconds": None,
        "figures": [],
        "notes": notes,
    }
    report["figures"] = make_figures(report, parity, figdir)
    report["runtime_seconds"] = round(time.perf_counter() - started, 1)
    EvaluationReport.model_validate(report)
    write_json(out, report)
    print(f"evaluate: selesai {report['runtime_seconds']} dtk -> {out}", flush=True)
    return report


def _r2(y: np.ndarray, p: np.ndarray) -> Optional[float]:
    denom = float(np.sum((y - np.mean(y)) ** 2))
    return None if denom == 0 else float(1 - np.sum((y - p) ** 2) / denom)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fp.evaluate")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--quick", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--figdir", default=None)
    parser.add_argument("--jobs", type=int, default=int(os.environ.get("EVAL_JOBS", DEFAULT_JOBS)))
    parser.add_argument("--seeds", type=int, default=None)
    parser.add_argument("--n-samples", type=int, default=5000)
    args = parser.parse_args(argv)
    report = run(quick=args.quick, out=args.out, figdir=args.figdir, jobs=args.jobs, seeds=args.seeds, n_samples=args.n_samples)
    cl = report["closed_loop"]["results"]["v1"]
    print("ringkasan v1:", {k: (cl[k]["median"], cl[k]["found_rate"]) for k in STRATEGIES})
    print("penghematan:", report["savings_estimate"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
