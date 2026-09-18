"""Unit tests for fp/palette.py (§17.1)"""
import pytest
import numpy as np
from fp.palette import (
    INGREDIENTS,
    PROCESS,
    FEATURES,
    load_palette,
    bounds,
    complete,
    validate,
    cost_idr_per_kg,
    meets_specs,
    sample_valid,
)

def test_load_palette():
    df = load_palette()
    assert len(df) == 11
    assert "GLYCERIN" in df["code"].values
    assert "AQUA" in df["code"].values

def test_bounds():
    b = bounds()
    assert b["GLYCERIN"] == (0.0, 10.0)
    assert b["RPM"] == (2000.0, 10000.0)
    assert b["TEMP"] == (60.0, 85.0)

def test_complete_and_validate_valid():
    formula = {
        "GLYCERIN": 5.0,
        "NIACINAMIDE": 4.0,
        "CETEARYL_ALCOHOL": 2.0,
        "EMULSIFIER": 3.0,
        "CCT": 8.0,
        "DIMETHICONE": 2.0,
        "XANTHAN": 0.2,
        "CARBOMER": 0.3,
        "NAOH": 0.45,
        "PHENOXYETHANOL": 0.8,
        "RPM": 5000.0,
        "HMIN": 3.0,
        "TEMP": 75.0,
    }
    f_comp = complete(formula)
    assert abs(f_comp["AQUA"] - (100.0 - (5+4+2+3+8+2+0.2+0.3+0.45+0.8))) < 1e-4
    assert f_comp["AQUA"] >= 50.0
    assert abs(f_comp["OIL_PHASE"] - (8.0 + 2.0 + 0.5 * 2.0)) < 1e-4
    
    v = validate(formula)
    assert len(v) == 0

def test_validate_violations():
    # Out of bounds & AQUA < 50
    bad_formula = {
        "GLYCERIN": 25.0, # max 10
        "CCT": 30.0,       # max 20
        "NIACINAMIDE": 4.0,
        "RPM": 1500.0,    # min 2000
    }
    v = validate(bad_formula)
    assert any("GLYCERIN" in err for err in v)
    assert any("CCT" in err for err in v)
    assert any("RPM" in err for err in v)
    assert any("AQUA" in err for err in v)

def test_cost_calculation():
    # Manual cost check
    formula = {
        "GLYCERIN": 10.0,    # 10% of 25000 = 2500
        "NIACINAMIDE": 5.0,   # 5% of 350000 = 17500
        "AQUA": 85.0          # 85% of 1000 = 850
    }
    expected = 2500.0 + 17500.0 + 850.0
    calculated = cost_idr_per_kg(formula)
    assert abs(calculated - expected) < 1e-2

def test_meets_specs():
    formula = {"NIACINAMIDE": 4.5, "GLYCERIN": 5.0}
    outputs = {
        "VISCOSITY_CP": 5000.0,
        "PH": 5.5,
        "D50_UM": 2.0,
        "STABLE": True,
        "COST_IDR_PER_KG": 40000.0,
    }
    specs = {
        "NIACINAMIDE_MIN_PCT": 4.0,
        "VISCOSITY_CP": [4000, 12000],
        "PH": [5.0, 6.5],
        "D50_UM_MAX": 3.0,
        "STABLE": True,
        "COST_IDR_PER_KG_MAX": 50000.0,
    }
    res = meets_specs(formula, outputs, specs)
    assert res["ALL"] is True
    assert res["NIACINAMIDE_MIN_PCT"] is True
    assert res["VISCOSITY_CP"] is True
    assert res["PH"] is True
    assert res["D50_UM_MAX"] is True
    assert res["STABLE"] is True
    assert res["COST_IDR_PER_KG_MAX"] is True

def test_sample_valid():
    rng = np.random.RandomState(42)
    df = sample_valid(50, rng=rng)
    assert len(df) == 50
    assert (df["AQUA"] >= 50.0).all()
    for _, row in df.iterrows():
        v = validate(row.to_dict())
        assert len(v) == 0
