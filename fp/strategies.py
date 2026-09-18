"""Strategi pemilihan batch berikutnya (PRD §10.2) + helper replay untuk backend (A-12).

Pemilik: Marshal (A); ditulis ulang Nico saat ambil alih.

    from fp import strategies as st
    known = st.select_initial(historical_df, specs, k=10, seed=0)   # 10 baris tanpa hit
    f = st.record_to_formula(row)                                   # dict kolom Formula (total 100)
    f = st.choose_ai(known_df, specs, seed)                          # Designer.fit(known) -> propose(n=1)
    f = st.choose_random(specs, rng) ; f = st.choose_heuristic(known_df, specs, rng)
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

from fp.designer import FORMULA_COLUMNS, Designer, _bounds_arrays, complete_frame, features, formula_matrix, sample_formulas, specs_dict
from fp.palette import INGREDIENTS, PROCESS, meets_specs

LAB_OUTPUT_KEYS = ("VISCOSITY_CP", "PH", "D50_UM", "STABILITY_INDEX", "STABLE", "COST_IDR_PER_KG")
HEURISTIC_STEP = 0.15
AI_N_SAMPLES = 5000
AI_MAXITER = 60
STRATEGIES = ("ai", "random", "heuristic")


# ---------------------------------------------------------------- helper replay (A-12)


def record_to_formula(record: Mapping[str, Any]) -> dict[str, float]:
    """Baris historis/pool -> dict kolom Formula (AQUA dihitung ulang agar total tepat 100)."""
    f = {k: float(record[k]) for k in INGREDIENTS + PROCESS}
    f["AQUA"] = round(100.0 - sum(f[k] for k in INGREDIENTS), 6)
    return {k: f[k] for k in FORMULA_COLUMNS}


def record_outputs(record: Mapping[str, Any]) -> dict[str, float]:
    return {k: float(record[k]) for k in LAB_OUTPUT_KEYS if k in record}


def specs_met(record: Mapping[str, Any], specs: Any) -> dict[str, bool]:
    return meets_specs(record_to_formula(record), record_outputs(record), specs_dict(specs))


def hit_mask(table: pd.DataFrame, specs: Any) -> np.ndarray:
    sp = specs_dict(specs)
    return np.array([bool(specs_met(r, sp)["ALL"]) for r in table.to_dict("records")], dtype=bool)


def select_initial(historical: pd.DataFrame, specs: Any, k: int = 10, seed: int = 0) -> pd.DataFrame:
    """k baris acak yang TIDAK memenuhi semua spesifikasi (titik awal replay/closed-loop)."""
    rng = np.random.RandomState(seed)
    candidates = np.flatnonzero(~hit_mask(historical, specs))
    if len(candidates) < k:
        raise ValueError(f"hanya {len(candidates)} baris tanpa hit, butuh {k}")
    idx = np.sort(rng.choice(candidates, size=k, replace=False))
    return historical.iloc[idx].reset_index(drop=True)


# ---------------------------------------------------------------- strategi (§10.2)


def choose_ai(known: pd.DataFrame, specs: Any, seed: int, n_samples: int = AI_N_SAMPLES) -> dict[str, float]:
    d = Designer(version="eval", seed=seed).fit(known, n_restarts_optimizer=0, maxiter=AI_MAXITER)
    cand = d.propose(specs, n=1, seed=seed, exclude=known[FORMULA_COLUMNS], n_samples=n_samples)
    return record_to_formula(cand.iloc[0])


def choose_random(specs: Any, rng: np.random.RandomState) -> dict[str, float]:
    sp = specs_dict(specs)
    m = sample_formulas(1, rng, float(sp.get("NIACINAMIDE_MIN_PCT", 0.0) or 0.0))
    return record_to_formula(complete_frame(m).iloc[0])


def choose_heuristic(known: pd.DataFrame, specs: Any, rng: np.random.RandomState, max_tries: int = 50) -> dict[str, float]:
    """Formula known dengan spesifikasi terpenuhi terbanyak (tie: biaya terendah); ubah SATU variabel ±15% lebar rentang."""
    base = best_known(known, specs)
    lo, hi = _bounds_arrays(0.0)
    x0 = formula_matrix(pd.DataFrame([base]))[0]
    for _ in range(max_tries):
        x = x0.copy()
        j = int(rng.randint(len(x)))
        x[j] = np.clip(x[j] + rng.choice([-1.0, 1.0]) * HEURISTIC_STEP * (hi[j] - lo[j]), lo[j], hi[j])
        if 100.0 - x[: len(INGREDIENTS)].sum() >= 50.0 and not np.allclose(x, x0):
            return record_to_formula(complete_frame(x[None, :]).iloc[0])
    return record_to_formula(base)


def best_known(known: pd.DataFrame, specs: Any) -> dict[str, Any]:
    sp = specs_dict(specs)
    rows = known.to_dict("records")
    scored = [
        (sum(v for k, v in specs_met(r, sp).items() if k != "ALL"), -float(r.get("COST_IDR_PER_KG", 0.0)), -i)
        for i, r in enumerate(rows)
    ]
    return rows[-max(scored)[2]]


def nearest_row(pool: pd.DataFrame, formula: Mapping[str, float], scaler: Any) -> int:
    """Indeks baris pool terdekat (ruang fitur ter-scale) dari sebuah formula."""
    Z = scaler.transform(features(pool))
    z = scaler.transform(features(pd.DataFrame([formula])))[0]
    return int(np.argmin(np.linalg.norm(Z - z, axis=1)))


def choose(
    strategy: str, known: pd.DataFrame, specs: Any, seed: int, rng: np.random.RandomState, n_samples: Optional[int] = None
) -> dict[str, float]:
    if strategy == "ai":
        return choose_ai(known, specs, seed, n_samples or AI_N_SAMPLES)
    if strategy == "random":
        return choose_random(specs, rng)
    if strategy == "heuristic":
        return choose_heuristic(known, specs, rng)
    raise ValueError(f"strategi tidak dikenal: {strategy}")
