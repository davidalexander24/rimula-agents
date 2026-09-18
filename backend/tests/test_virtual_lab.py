"""Unit tests for fp/virtual_lab.py (§17.1)"""
import pytest
import numpy as np
from fp.virtual_lab import VirtualLab, _build_default_variants
from fp.palette import sample_valid, meets_specs, load_palette

def test_variants_creation():
    all_v = _build_default_variants()
    assert "v1" in all_v
    assert "v2" in all_v
    assert "v3" in all_v

def test_true_mean_deterministic():
    lab = VirtualLab("v1", seed=42)
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
    m1 = lab.true_mean(formula)
    m2 = lab.true_mean(formula)
    assert m1["VISCOSITY_CP"] == m2["VISCOSITY_CP"]
    assert m1["PH"] == m2["PH"]
    assert m1["D50_UM"] == m2["D50_UM"]

def test_run_batch_reproducible_seed():
    lab1 = VirtualLab("v1", seed=100)
    lab2 = VirtualLab("v1", seed=100)
    formula = {"GLYCERIN": 5.0, "NIACINAMIDE": 4.0, "RPM": 5000.0, "HMIN": 3.0, "TEMP": 75.0}
    r1 = lab1.run_batch(formula)
    r2 = lab2.run_batch(formula)
    assert r1["VISCOSITY_CP"] == r2["VISCOSITY_CP"]
    assert r1["PH"] == r2["PH"]

def test_qualitative_relationships():
    lab = VirtualLab("v1", seed=42)
    # 1. Neutralized Carbomer increases viscosity
    f_base = {"GLYCERIN": 5.0, "CARBOMER": 0.1, "NAOH": 0.15, "RPM": 4000.0, "HMIN": 3.0, "TEMP": 75.0}
    f_high_carb = {"GLYCERIN": 5.0, "CARBOMER": 0.4, "NAOH": 0.6, "RPM": 4000.0, "HMIN": 3.0, "TEMP": 75.0}
    m_base = lab.true_mean(f_base)
    m_high_carb = lab.true_mean(f_high_carb)
    assert m_high_carb["VISCOSITY_CP"] > m_base["VISCOSITY_CP"]

    # 2. RPM increase reduces D50 droplet size
    f_low_rpm = {"CCT": 10.0, "EMULSIFIER": 2.0, "RPM": 3000.0, "HMIN": 3.0, "TEMP": 75.0}
    f_high_rpm = {"CCT": 10.0, "EMULSIFIER": 2.0, "RPM": 8000.0, "HMIN": 3.0, "TEMP": 75.0}
    assert lab.true_mean(f_high_rpm)["D50_UM"] < lab.true_mean(f_low_rpm)["D50_UM"]

def test_calibration_hit_rate_v1():
    # Hit rate on 1,000 samples for brief niacinamide_gel_cream in [0.03, 0.15]
    lab = VirtualLab("v1", seed=20260917)
    df_samples = sample_valid(1000, rng=np.random.RandomState(20260917))
    specs = {
        "NIACINAMIDE_MIN_PCT": 4.0,
        "VISCOSITY_CP": [4000, 12000],
        "PH": [5.0, 6.5],
        "D50_UM_MAX": 3.0,
        "STABLE": True,
        "COST_IDR_PER_KG_MAX": 50000,
    }
    hits = 0
    for _, row in df_samples.iterrows():
        out = lab.run_batch(row.to_dict())
        chk = meets_specs(row.to_dict(), out, specs)
        if chk["ALL"]:
            hits += 1
    hit_rate = hits / len(df_samples)
    assert 0.02 <= hit_rate <= 0.15
