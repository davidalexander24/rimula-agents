"""Test Guardian (PRD §11, §17.1). Pemilik: Nico (D)."""

from __future__ import annotations

import importlib
import math
import re

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import StandardScaler

from fp import guardian
from fp.schemas import INGREDIENT_FIELDS, Gate

BOUNDS = {
    "GLYCERIN": (0, 10),
    "NIACINAMIDE": (0, 10),
    "CETEARYL_ALCOHOL": (0, 5),
    "EMULSIFIER": (0, 6),
    "CCT": (0, 20),
    "DIMETHICONE": (0, 5),
    "XANTHAN": (0, 1),
    "CARBOMER": (0, 0.5),
    "NAOH": (0, 1),
    "PHENOXYETHANOL": (0.3, 1),
    "RPM": (2000, 10000),
    "HMIN": (1, 10),
    "TEMP": (60, 85),
}

SPECS = {
    "NIACINAMIDE_MIN_PCT": 4.0,
    "VISCOSITY_CP": [4000, 12000],
    "PH": [5.0, 6.5],
    "D50_UM_MAX": 3.0,
    "STABLE": True,
    "COST_IDR_PER_KG_MAX": 50000,
}

# Sama dengan contracts/fixtures/candidate_review.json
BASE_FORMULA = {
    "GLYCERIN": 3.0,
    "NIACINAMIDE": 4.5,
    "CETEARYL_ALCOHOL": 1.5,
    "EMULSIFIER": 2.5,
    "CCT": 5.0,
    "DIMETHICONE": 1.0,
    "XANTHAN": 0.3,
    "CARBOMER": 0.3,
    "NAOH": 0.5,
    "PHENOXYETHANOL": 0.8,
    "AQUA": 80.6,
    "RPM": 7000.0,
    "HMIN": 5.0,
    "TEMP": 75.0,
}

BASE_PREDICTION = {
    "VISCOSITY_CP": 6453.0,
    "VISCOSITY_CP_CI95": [3755.0, 11091.0],
    "PH": 5.62,
    "PH_CI95": [5.33, 5.91],
    "D50_UM": 1.24,
    "D50_UM_CI95": [0.83, 1.83],
    "P_STABLE": 0.84,
    "COST_IDR_PER_KG": 28346.0,
    "P_SPECS": {"P_VISC": 0.72, "P_PH": 0.97, "P_D50": 0.99, "P_STABLE": 0.84, "DET_OK": 1.0},
    "P_TARGET": 0.581,
    "UNCERTAINTY": 0.48,
    "model_version": "gp-global-v1",
}

REGULATORY_NO_HALAL = pd.DataFrame(
    [
        {
            "code": "PHENOXYETHANOL",
            "max_pct": 1.0,
            "halal_risk": "low",
            "note": "batas kadar pengawet",
            "source_to_verify": "",
            "verified": False,
        }
    ]
)

ALL_CODES = {
    "NON_FINITE", "OUT_OF_BOUNDS", "WATER_BELOW_MIN", "TOTAL_NOT_100", "OVER_REG_MAX", "CLAIM_NOT_MET",
    "BUDGET_EXCEEDED", "CARBOMER_NOT_NEUTRALIZED", "NIACINAMIDE_LOW_PH", "NO_PREDICTION", "HIGH_UNCERTAINTY",
    "LOW_P_TARGET", "EXTRAPOLATION", "HALAL_SOURCE_CHECK", "UNCOMMON_COMBINATION",
}

FORBIDDEN_CLAIMS = re.compile(
    r"\b(aman|dijamin|terjamin|lolos bpom|formula terbaik|bersertifikat halal|produk halal|pasti halal|terbukti halal)\b",
    re.IGNORECASE,
)

SEEN_CODES: set[str] = set()


def ctx(**overrides):
    kwargs = dict(bounds=BOUNDS, regulatory=REGULATORY_NO_HALAL, unc_max=0.9, market=None)
    kwargs.update(overrides)
    specs = kwargs.pop("specs", SPECS)
    return guardian.build_context(specs, **kwargs)


def run(formula=None, prediction="base", context=None) -> Gate:
    f = dict(BASE_FORMULA, **(formula or {}))
    p = BASE_PREDICTION if prediction == "base" else prediction
    gate = guardian.check(f, p, context or ctx())
    for issue in gate.issues:
        SEEN_CODES.add(issue.code)
        assert not FORBIDDEN_CLAIMS.search(issue.message), issue.message
    return gate


def codes(gate: Gate) -> list[str]:
    return [i.code for i in gate.issues]


def rebalance(**changes) -> dict:
    """Ubah bahan lalu hitung ulang AQUA agar total tetap 100."""
    f = dict(BASE_FORMULA, **changes)
    f["AQUA"] = round(100.0 - sum(f[k] for k in INGREDIENT_FIELDS), 6)
    return f


def test_clean_formula_passes():
    gate = run()
    assert gate.status == "pass"
    assert gate.issues == []


def test_non_finite_blocks_immediately():
    gate = run({"GLYCERIN": math.nan})
    assert gate.status == "blocked"
    assert codes(gate) == ["NON_FINITE"]
    assert run({"RPM": math.inf}).issues[0].field == "RPM"


def test_missing_field_is_non_finite():
    f = dict(BASE_FORMULA)
    del f["TEMP"]
    gate = guardian.check(f, BASE_PREDICTION, ctx())
    SEEN_CODES.update(codes(gate))
    assert codes(gate) == ["NON_FINITE"]


def test_out_of_bounds():
    gate = run(rebalance(XANTHAN=1.5))
    assert gate.status == "blocked"
    issue = next(i for i in gate.issues if i.code == "OUT_OF_BOUNDS")
    assert issue.field == "XANTHAN"
    assert "0–1" in issue.message
    assert "OUT_OF_BOUNDS" in codes(run({"RPM": 12000}))


def test_water_below_min():
    gate = run(rebalance(CCT=20, GLYCERIN=10, EMULSIFIER=6, CETEARYL_ALCOHOL=5, DIMETHICONE=5))
    assert "WATER_BELOW_MIN" in codes(gate)
    assert gate.status == "blocked"


def test_total_not_100():
    gate = run({"AQUA": 70.0})
    assert "TOTAL_NOT_100" in codes(gate)
    assert gate.status == "blocked"


def test_total_tolerance():
    assert "TOTAL_NOT_100" not in codes(run({"AQUA": 80.6005}))


def test_over_regulatory_max():
    regulatory = pd.DataFrame(
        [{"code": "PHENOXYETHANOL", "max_pct": 0.5, "halal_risk": "low", "note": "", "source_to_verify": "", "verified": False}]
    )
    gate = run(context=ctx(regulatory=regulatory))
    issue = next(i for i in gate.issues if i.code == "OVER_REG_MAX")
    assert issue.field == "PHENOXYETHANOL"
    assert "asumsi tim" in issue.message
    assert gate.status == "blocked"


def test_claim_not_met():
    gate = run(rebalance(NIACINAMIDE=3.0))
    assert "CLAIM_NOT_MET" in codes(gate)
    assert gate.status == "blocked"


def test_budget_exceeded_uses_prediction_cost():
    gate = run(prediction=dict(BASE_PREDICTION, COST_IDR_PER_KG=60000.0))
    assert "BUDGET_EXCEEDED" in codes(gate)
    assert gate.status == "blocked"


def test_carbomer_not_neutralized_is_warning():
    gate = run(rebalance(NAOH=0.1))
    assert codes(gate) == ["CARBOMER_NOT_NEUTRALIZED"]
    assert gate.status == "review"
    assert "CARBOMER_NOT_NEUTRALIZED" not in codes(run(rebalance(CARBOMER=0.04, NAOH=0.0)))


def test_niacinamide_low_ph():
    gate = run(rebalance(NIACINAMIDE=6.0), prediction=dict(BASE_PREDICTION, PH=5.2))
    assert "NIACINAMIDE_LOW_PH" in codes(gate)
    low_nia = run(rebalance(NIACINAMIDE=4.5), prediction=dict(BASE_PREDICTION, PH=5.2))
    assert "NIACINAMIDE_LOW_PH" not in codes(low_nia)


def test_no_prediction():
    gate = run(prediction=None, context=ctx(specs={**SPECS, "COST_IDR_PER_KG_MAX": 1e9}))
    assert codes(gate) == ["NO_PREDICTION"]
    assert gate.status == "review"


def test_high_uncertainty_needs_unc_max():
    pred = dict(BASE_PREDICTION, UNCERTAINTY=1.5)
    assert "HIGH_UNCERTAINTY" in codes(run(prediction=pred))
    assert "HIGH_UNCERTAINTY" not in codes(run(prediction=pred, context=ctx(unc_max=None)))


def test_low_p_target():
    gate = run(prediction=dict(BASE_PREDICTION, P_TARGET=0.01))
    assert codes(gate) == ["LOW_P_TARGET"]


def test_extrapolation():
    rng = np.random.RandomState(0)
    rows = []
    for _ in range(60):
        f = dict(BASE_FORMULA)
        for k in ("GLYCERIN", "CCT"):
            f[k] = BASE_FORMULA[k] + rng.normal(0, 0.3)
        f["RPM"] = BASE_FORMULA["RPM"] + rng.normal(0, 200)
        rows.append(guardian.feature_vector(f))
    X = np.vstack(rows)
    scaler = StandardScaler().fit(X)
    context = ctx(train_X_scaled=scaler.transform(X), scaler=scaler)
    assert context.nn_threshold is not None and context.nn_threshold > 0
    assert "EXTRAPOLATION" not in codes(run(context=context))
    far = run(rebalance(GLYCERIN=9.0, CCT=15.0) | {"RPM": 2500.0}, context=context)
    assert "EXTRAPOLATION" in codes(far)


def test_halal_source_check_from_csv():
    regulatory = guardian.load_regulatory()
    gate = run(context=ctx(regulatory=regulatory))
    halal = [i for i in gate.issues if i.code == "HALAL_SOURCE_CHECK"]
    assert {i.field for i in halal} == {"GLYCERIN", "EMULSIFIER", "CETEARYL_ALCOHOL"}
    assert all(i.message.endswith("(asumsi tim).") for i in halal)
    assert gate.status == "review"
    no_glycerin = run(rebalance(GLYCERIN=0.0), context=ctx(regulatory=regulatory))
    assert "GLYCERIN" not in {i.field for i in no_glycerin.issues}


def test_uncommon_combination_is_info_only():
    present = sorted(k for k in INGREDIENT_FIELDS if BASE_FORMULA[k] >= 0.1)
    pair_support = {f"{a}|{b}": 50 for i, a in enumerate(present) for b in present[i + 1 :]}
    pair_support["CARBOMER|NIACINAMIDE"] = 1
    gate = run(context=ctx(market={"pair_support": pair_support}))
    assert codes(gate) == ["UNCOMMON_COMBINATION"]
    assert gate.issues[0].severity == "info"
    assert "CARBOMER+NIACINAMIDE" in gate.issues[0].message and "OBF: 1" in gate.issues[0].message
    assert gate.status == "pass"
    pair_support["CARBOMER|NIACINAMIDE"] = 3
    assert run(context=ctx(market={"pair_support": pair_support})).issues == []


def test_market_not_ready_skips_combination():
    assert "UNCOMMON_COMBINATION" not in codes(run(context=ctx(market={})))


def test_status_order():
    both = run(rebalance(NIACINAMIDE=3.0, NAOH=0.1))
    assert {"CLAIM_NOT_MET", "CARBOMER_NOT_NEUTRALIZED"} <= set(codes(both))
    assert both.status == "blocked"
    assert guardian.status_from_issues([]) == "pass"


def test_regulatory_csv_shape():
    df = guardian.load_regulatory()
    assert list(df.columns) == list(guardian.REGULATORY_COLUMNS)
    assert set(INGREDIENT_FIELDS) <= set(df["code"])
    assert not df["verified"].any()
    assert df.loc[df["code"] == "PHENOXYETHANOL", "max_pct"].item() == 1.0


def test_build_context_with_real_palette():
    context = guardian.build_context(SPECS)
    assert context.bounds["PHENOXYETHANOL"] == (0.3, 1.0)
    assert guardian.check(BASE_FORMULA, BASE_PREDICTION, context).status == "review"


def test_direct_context_like_backend():
    """Pola panggilan David (request david-1724): dataclass langsung, specs dict, regulatory/nn_threshold None."""
    rng = np.random.RandomState(1)
    X = np.vstack([guardian.feature_vector(BASE_FORMULA) + rng.normal(0, 0.1, 14) for _ in range(20)])
    scaler = StandardScaler().fit(X)
    context = guardian.GuardianContext(
        specs=dict(SPECS),
        bounds=None,
        regulatory=None,
        unc_max=None,
        train_X_scaled=scaler.transform(X),
        scaler=scaler,
        nn_threshold=None,
        market=None,
    )
    assert context.nn_threshold is not None and len(context.regulatory) >= 10
    gate = guardian.check(dict(BASE_FORMULA), dict(BASE_PREDICTION), context)
    assert gate.status == "review"
    assert {i.code for i in gate.issues} >= {"HALAL_SOURCE_CHECK"}
    assert guardian.check(rebalance(NIACINAMIDE=3.0), None, context).status == "blocked"


@pytest.mark.parametrize("module", ["fp.market", "fp.scout"])
def test_evidence_modules_import(module):
    mod = importlib.import_module(module)
    assert isinstance(mod.status()["ready"], bool)


def test_zz_every_code_triggered():
    missing = ALL_CODES - SEEN_CODES
    assert not missing, f"kode belum terpicu: {sorted(missing)}"
