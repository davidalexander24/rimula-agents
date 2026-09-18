"""Guardian agent: pemeriksa formula berbasis aturan (PRD §11). Pemilik: Nico (D).

Guardian tidak pernah menyimpulkan "halal", "aman", atau "lolos BPOM". Aturan dari
`data/assumptions/regulatory.csv` selalu disebut sebagai "asumsi tim".

    from fp import guardian
    ctx = guardian.build_context(specs, unc_max=0.9, train_X_scaled=X, scaler=scaler, market=stats)
    gate = guardian.check(formula, prediction, ctx)   # -> fp.schemas.Gate
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Union

import numpy as np
import pandas as pd

from fp.schemas import INGREDIENT_FIELDS, PROCESS_FIELDS, Formula, Gate, Issue, Prediction, Specs

AQUA_MIN_PCT = 50.0
TOTAL_TOL = 1e-3
BOUND_TOL = 1e-6
CARBOMER_ACTIVE_PCT = 0.05
NAOH_PER_CARBOMER_MIN = 0.75
NIACINAMIDE_HIGH_PCT = 5.0
PH_LOW = 5.5
P_TARGET_LOW = 0.05
HALAL_RISK_FLAGGED = ("medium", "high")
COMBINATION_MIN_PCT = 0.1
COMBINATION_MIN_SUPPORT = 3
NN_PERCENTILE = 95

# Fitur untuk cek ekstrapolasi; urutan sama dengan palette.FEATURES (§8.1.1).
FEATURES: tuple[str, ...] = INGREDIENT_FIELDS + PROCESS_FIELDS + ("OIL_PHASE",)

REGULATORY_COLUMNS = ("code", "max_pct", "halal_risk", "note", "source_to_verify", "verified")

FormulaLike = Union[Formula, Mapping[str, Any]]
PredictionLike = Union[Prediction, Mapping[str, Any], None]
SpecsLike = Union[Specs, Mapping[str, Any], None]


@dataclass
class GuardianContext:
    """Konteks Guardian (§11.1). Dibangun backend saat startup dan saat model berganti.

    Boleh dibuat langsung: `specs` dict -> Specs, `bounds=None` -> palette.bounds(),
    `regulatory=None` -> regulatory.csv, `nn_threshold=None` + train_X_scaled -> persentil 95.
    """

    specs: Optional[Specs] = None
    bounds: Optional[Mapping[str, tuple[float, float]]] = None
    regulatory: Optional[pd.DataFrame] = None
    unc_max: Optional[float] = None
    train_X_scaled: Optional[np.ndarray] = None
    scaler: Any = None
    nn_threshold: Optional[float] = None
    market: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        self.specs = _as_specs(self.specs)
        if self.bounds is None:
            from fp import palette

            self.bounds = palette.bounds()
        self.bounds = {k: (float(lo), float(hi)) for k, (lo, hi) in self.bounds.items()}
        if self.regulatory is None:
            self.regulatory = load_regulatory()
        if self.train_X_scaled is not None:
            self.train_X_scaled = np.asarray(self.train_X_scaled, dtype=float)
            if self.nn_threshold is None:
                self.nn_threshold = compute_nn_threshold(self.train_X_scaled)


# ---------------------------------------------------------------- pemuatan data


def load_regulatory(path: Optional[Union[str, Path]] = None) -> pd.DataFrame:
    """Baca regulatory.csv (§8.5). `max_pct` kosong -> NaN, `halal_risk` huruf kecil."""
    if path is None:
        from fp.config import get_settings

        path = get_settings().regulatory_csv
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for col in REGULATORY_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["code"] = df["code"].str.strip().str.upper()
    df["max_pct"] = pd.to_numeric(df["max_pct"].replace("", np.nan), errors="coerce")
    df["halal_risk"] = df["halal_risk"].str.strip().str.lower()
    df["note"] = df["note"].str.strip()
    df["verified"] = df["verified"].str.strip().str.lower().eq("true")
    return df[list(REGULATORY_COLUMNS)]


def feature_vector(formula: FormulaLike) -> np.ndarray:
    """14 fitur (§8.1.1) dari formula; AQUA tidak dipakai, OIL_PHASE dihitung."""
    f = _as_dict(formula)
    oil = _num(f, "CCT") + _num(f, "DIMETHICONE") + 0.5 * _num(f, "CETEARYL_ALCOHOL")
    values = [_num(f, k) for k in INGREDIENT_FIELDS + PROCESS_FIELDS] + [oil]
    return np.asarray(values, dtype=float)


def compute_nn_threshold(train_X_scaled: np.ndarray, percentile: float = NN_PERCENTILE) -> Optional[float]:
    """Persentil jarak nearest-neighbor antar-data training (ter-scale)."""
    X = np.asarray(train_X_scaled, dtype=float)
    if X.ndim != 2 or len(X) < 2:
        return None
    from sklearn.neighbors import NearestNeighbors

    nn = NearestNeighbors(n_neighbors=2).fit(X)
    dist, _ = nn.kneighbors(X)
    return float(np.percentile(dist[:, 1], percentile))


def build_context(
    specs: SpecsLike = None,
    *,
    bounds: Optional[Mapping[str, tuple[float, float]]] = None,
    regulatory: Optional[pd.DataFrame] = None,
    unc_max: Optional[float] = None,
    train_X_scaled: Optional[np.ndarray] = None,
    scaler: Any = None,
    nn_threshold: Optional[float] = None,
    market: Optional[Mapping[str, Any]] = None,
) -> GuardianContext:
    """Seperti GuardianContext(...), ditambah `unc_max=None` -> UNC_MAX dari .env."""
    if unc_max is None:
        from fp.config import get_settings

        unc_max = get_settings().unc_max
    return GuardianContext(
        specs=specs,
        bounds=bounds,
        regulatory=regulatory,
        unc_max=unc_max,
        train_X_scaled=train_X_scaled,
        scaler=scaler,
        nn_threshold=nn_threshold,
        market=market,
    )


# ---------------------------------------------------------------- pemeriksaan


def check(formula: FormulaLike, prediction: PredictionLike, ctx: GuardianContext) -> Gate:
    """Periksa satu formula (§11.2). `prediction` boleh None."""
    f = _as_dict(formula)
    pred = _as_dict(prediction) if prediction is not None else None
    issues: list[Issue] = []

    bad = [k for k in INGREDIENT_FIELDS + PROCESS_FIELDS + ("AQUA",) if k in f and not _finite(f[k])]
    missing = [k for k in INGREDIENT_FIELDS + PROCESS_FIELDS if k not in f]
    if bad or missing:
        field_name = (bad + missing)[0]
        issues.append(_issue("NON_FINITE", "error", "Nilai formula tidak valid.", field_name))
        return _gate(issues)

    ingredients_sum = sum(_num(f, k) for k in INGREDIENT_FIELDS)
    aqua = _num(f, "AQUA") if "AQUA" in f else 100.0 - ingredients_sum

    # Palet & komposisi
    for k in INGREDIENT_FIELDS + PROCESS_FIELDS:
        if k not in ctx.bounds:
            continue
        lo, hi = ctx.bounds[k]
        v = _num(f, k)
        if v < lo - BOUND_TOL or v > hi + BOUND_TOL:
            issues.append(_issue("OUT_OF_BOUNDS", "error", f"{k} di luar rentang palet ({_fmt(lo)}–{_fmt(hi)}).", k))
    if aqua < AQUA_MIN_PCT - BOUND_TOL:
        issues.append(_issue("WATER_BELOW_MIN", "error", "Kadar air di bawah 50%.", "AQUA"))
    if abs(ingredients_sum + aqua - 100.0) > TOTAL_TOL:
        issues.append(_issue("TOTAL_NOT_100", "error", "Total komposisi tidak 100%.", None))

    # Batas regulasi (asumsi tim)
    reg = ctx.regulatory if ctx.regulatory is not None else pd.DataFrame(columns=list(REGULATORY_COLUMNS))
    for row in reg.itertuples(index=False):
        code = str(row.code)
        if code not in f or pd.isna(row.max_pct):
            continue
        if _num(f, code) > float(row.max_pct) + BOUND_TOL:
            issues.append(
                _issue(
                    "OVER_REG_MAX",
                    "error",
                    f"{code} melebihi batas {_fmt(float(row.max_pct))}% (asumsi tim, perlu verifikasi).",
                    code,
                )
            )

    # Brief: klaim & anggaran
    specs = ctx.specs
    if specs is not None:
        if _num(f, "NIACINAMIDE") < specs.NIACINAMIDE_MIN_PCT - BOUND_TOL:
            issues.append(_issue("CLAIM_NOT_MET", "error", "Kadar niacinamide di bawah klaim brief.", "NIACINAMIDE"))
        cost = _cost(f, pred)
        if cost is not None and cost > specs.COST_IDR_PER_KG_MAX + BOUND_TOL:
            issues.append(
                _issue("BUDGET_EXCEEDED", "error", "Biaya bahan melebihi anggaran brief (harga asumsi).", "COST_IDR_PER_KG")
            )

    # Formulasi
    carbomer = _num(f, "CARBOMER")
    if carbomer > CARBOMER_ACTIVE_PCT and _num(f, "NAOH") < NAOH_PER_CARBOMER_MIN * carbomer:
        issues.append(_issue("CARBOMER_NOT_NEUTRALIZED", "warning", "Carbomer kemungkinan belum dinetralkan.", "CARBOMER"))

    # Prediksi
    if pred is None:
        issues.append(_issue("NO_PREDICTION", "warning", "Prediksi belum tersedia.", None))
    else:
        ph = pred.get("PH")
        if _num(f, "NIACINAMIDE") >= NIACINAMIDE_HIGH_PCT and _finite(ph) and float(ph) < PH_LOW:
            issues.append(
                _issue(
                    "NIACINAMIDE_LOW_PH",
                    "warning",
                    "Niacinamide tinggi pada pH rendah — risiko stabilitas (perlu uji).",
                    "NIACINAMIDE",
                )
            )
        unc = pred.get("UNCERTAINTY")
        if ctx.unc_max is not None and _finite(unc) and float(unc) > ctx.unc_max:
            issues.append(
                _issue("HIGH_UNCERTAINTY", "warning", "Ketidakpastian model tinggi — wajib uji lab.", "UNCERTAINTY")
            )
        p_target = pred.get("P_TARGET")
        if _finite(p_target) and float(p_target) < P_TARGET_LOW:
            issues.append(
                _issue("LOW_P_TARGET", "warning", "Peluang memenuhi seluruh spesifikasi rendah.", "P_TARGET")
            )

    # Ekstrapolasi terhadap data training Designer
    distance = _nn_distance(f, ctx)
    if distance is not None and ctx.nn_threshold is not None and distance > ctx.nn_threshold:
        issues.append(_issue("EXTRAPOLATION", "warning", "Formula jauh dari data yang pernah diuji.", None))

    # Catatan sumber bahan (asumsi tim)
    for row in reg.itertuples(index=False):
        code = str(row.code)
        if row.halal_risk in HALAL_RISK_FLAGGED and code in f and _num(f, code) > 0:
            note = str(row.note).strip() or "sumber bahan perlu dicek"
            issues.append(_issue("HALAL_SOURCE_CHECK", "warning", f"{code}: {note} (asumsi tim).", code))

    # Kelaziman kombinasi di produk nyata (Open Beauty Facts)
    weakest = _weakest_pair(f, ctx.market)
    if weakest is not None:
        a, b, n = weakest
        if n < COMBINATION_MIN_SUPPORT:
            issues.append(
                _issue(
                    "UNCOMMON_COMBINATION",
                    "info",
                    f"Kombinasi {a}+{b} jarang ditemukan di produk nyata (OBF: {n}).",
                    f"{a}|{b}",
                )
            )

    return _gate(issues)


def status_from_issues(issues: list[Issue]) -> str:
    """error -> blocked; warning -> review; hanya info/kosong -> pass."""
    severities = {i.severity for i in issues}
    if "error" in severities:
        return "blocked"
    if "warning" in severities:
        return "review"
    return "pass"


# ---------------------------------------------------------------- helper


def _gate(issues: list[Issue]) -> Gate:
    return Gate(status=status_from_issues(issues), issues=issues)


def _issue(code: str, severity: str, message: str, field_name: Optional[str]) -> Issue:
    return Issue(code=code, severity=severity, message=message, field=field_name)


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj)


def _as_specs(specs: SpecsLike) -> Optional[Specs]:
    if specs is None or isinstance(specs, Specs):
        return specs
    return Specs.model_validate(specs)


def _finite(v: Any) -> bool:
    try:
        return v is not None and not isinstance(v, bool) and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _num(f: Mapping[str, Any], key: str) -> float:
    return float(f.get(key, 0.0) or 0.0)


def _fmt(x: float) -> str:
    return f"{x:g}"


def _cost(f: Mapping[str, Any], pred: Optional[Mapping[str, Any]]) -> Optional[float]:
    if pred is not None and _finite(pred.get("COST_IDR_PER_KG")):
        return float(pred["COST_IDR_PER_KG"])
    try:
        from fp import palette

        return float(palette.cost_idr_per_kg(dict(f)))
    except Exception:  # palet belum siap -> anggaran tidak diperiksa
        return None


def _nn_distance(f: Mapping[str, Any], ctx: GuardianContext) -> Optional[float]:
    if ctx.train_X_scaled is None or ctx.scaler is None or len(ctx.train_X_scaled) == 0:
        return None
    x = ctx.scaler.transform(feature_vector(f).reshape(1, -1))
    return float(np.min(np.linalg.norm(ctx.train_X_scaled - x, axis=1)))


def _weakest_pair(f: Mapping[str, Any], market: Optional[Mapping[str, Any]]) -> Optional[tuple[str, str, int]]:
    """Pasangan bahan (pct ≥ 0,1, tanpa AQUA) dengan support paling kecil; None bila market belum siap."""
    if not market or not isinstance(market.get("pair_support"), Mapping):
        return None
    pair_support = market["pair_support"]
    codes = sorted(k for k in INGREDIENT_FIELDS if _num(f, k) >= COMBINATION_MIN_PCT)
    weakest: Optional[tuple[str, str, int]] = None
    for i, a in enumerate(codes):
        for b in codes[i + 1 :]:
            n = int(pair_support.get(f"{a}|{b}", 0) or 0)
            if weakest is None or n < weakest[2]:
                weakest = (a, b, n)
    return weakest
