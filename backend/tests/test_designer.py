"""Test Designer & registry (PRD §9, §17.1). Pemilik: Marshal (A); ditulis Nico saat ambil alih."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from fp import registry
from fp.designer import FORMULA_COLUMNS, P_COLUMNS, PREDICT_COLUMNS, Designer
from fp.palette import INGREDIENTS, bounds

SPECS = {
    "NIACINAMIDE_MIN_PCT": 4.0,
    "VISCOSITY_CP": [4000, 12000],
    "PH": [5.0, 6.5],
    "D50_UM_MAX": 3.0,
    "STABLE": True,
    "COST_IDR_PER_KG_MAX": 50000,
}
TARGETS = ["VISCOSITY_CP", "PH", "D50_UM", "STABILITY_INDEX"]


@pytest.fixture(scope="module")
def hist(fp_home):
    return pd.read_csv(fp_home / "data" / "virtual_lab" / "historical_v1.csv")


@pytest.fixture(scope="module")
def model(hist):
    started = time.perf_counter()
    d = Designer(version="gp-test-v1").fit(hist.iloc[:100], n_restarts_optimizer=0)
    d.fit_wall = time.perf_counter() - started
    return d


def test_fit_100_rows_fast(model):
    assert model.fit_wall < 20
    assert model.n_train == 100 and model.fitted
    assert model.train_X_scaled.shape == (100, 14)


def test_fit_accepts_single_table_and_split(hist):
    a = Designer().fit(hist.iloc[:30], n_restarts_optimizer=0)
    b = Designer().fit(hist.iloc[:30][FORMULA_COLUMNS], hist.iloc[:30][TARGETS], n_restarts_optimizer=0)
    assert np.allclose(a.predict(hist.iloc[30:35])["PH"], b.predict(hist.iloc[30:35])["PH"])


def test_predict_columns_and_intervals(model, hist):
    p = model.predict(hist.iloc[100:120])
    assert set(PREDICT_COLUMNS) <= set(p.columns)
    for base in ("VISCOSITY_CP", "PH", "D50_UM"):
        assert (p[f"{base}_LO"] <= p[base] + 1e-9).all() and (p[base] <= p[f"{base}_HI"] + 1e-9).all()
    assert p["P_STABLE"].between(0, 1).all()
    assert (p["UNCERTAINTY"] >= 0).all()


def test_cost_matches_palette(model, hist):
    from fp import palette

    row = hist.iloc[0].to_dict()
    assert model.predict(hist.iloc[:1])["COST_IDR_PER_KG"].item() == pytest.approx(palette.cost_idr_per_kg(row), abs=0.02)


def test_p_specs_range(model, hist):
    s = model.p_specs(hist.iloc[100:140], SPECS)
    assert set(P_COLUMNS) <= set(s.columns)
    assert s["P_TARGET"].between(0, 1).all()
    low_nia = s[s["NIACINAMIDE"] < 4.0]
    assert (low_nia["DET_OK"] == 0).all() and (low_nia["P_TARGET"] == 0).all()


def test_propose_valid_diverse_and_respects_claim(model):
    c = model.propose(SPECS, n=3, seed=7, n_samples=3000)
    assert len(c) == 3
    assert set(FORMULA_COLUMNS) <= set(c.columns) and "reason" in c.columns
    assert np.allclose(c[INGREDIENTS].sum(axis=1) + c["AQUA"], 100.0, atol=1e-6)
    assert (c["AQUA"] >= 50).all()
    assert (c["NIACINAMIDE"] >= 4.0 - 1e-9).all()
    b = bounds()
    for col in INGREDIENTS + ["RPM", "HMIN", "TEMP"]:
        assert c[col].between(b[col][0] - 1e-6, b[col][1] + 1e-6).all(), col
    Z = model.transform(c)
    assert min(np.linalg.norm(Z[i] - Z[j]) for i in range(3) for j in range(i + 1, 3)) >= 0.6
    again = model.propose(SPECS, n=3, seed=7, n_samples=3000)
    assert np.allclose(again[FORMULA_COLUMNS].to_numpy(), c[FORMULA_COLUMNS].to_numpy())


def test_propose_excludes_known(model):
    first = model.propose(SPECS, n=1, seed=3, n_samples=2000)
    second = model.propose(SPECS, n=1, seed=3, n_samples=2000, exclude=first[FORMULA_COLUMNS])
    assert not np.allclose(first[FORMULA_COLUMNS].to_numpy(), second[FORMULA_COLUMNS].to_numpy())


def test_rank_pool_no_leak(model, hist):
    pool = hist.iloc[200:260]
    r = model.rank_pool(pool, SPECS, n=3)
    assert len(r) == 3 and "record_id" in r.columns
    assert set(r["record_id"]) <= set(pool["record_id"])
    true_visc = pool.set_index("record_id").loc[r["record_id"], "VISCOSITY_CP"].to_numpy()
    assert not np.allclose(r["VISCOSITY_CP"].to_numpy(), true_visc)  # kolom = prediksi, bukan hasil lab
    assert "STABILITY_INDEX" not in r.columns


def test_warm_start_retrain(model, hist):
    started = time.perf_counter()
    d2 = Designer(version="gp-test-v2").fit(hist.iloc[:101], prev=model, n_restarts_optimizer=0)
    assert time.perf_counter() - started < 10
    assert d2.parent_version == "gp-test-v1" and d2.n_train == 101


def test_save_load_identical(model, hist, runtime_dir):
    path = model.save(runtime_dir / "models" / "gp-test-v1.joblib")
    assert path.with_suffix(".json").exists()
    loaded = Designer.load(path)
    a, b = model.predict(hist.iloc[:5]), loaded.predict(hist.iloc[:5])
    assert np.allclose(a["VISCOSITY_CP"], b["VISCOSITY_CP"]) and np.allclose(a["P_STABLE"], b["P_STABLE"])


def test_registry_roundtrip(model, runtime_dir):
    mdir, bdir = runtime_dir / "models", runtime_dir / "base"
    registry.register(model, model_dir=mdir, base_dir=bdir)
    meta = registry.latest("global", model_dir=mdir, base_dir=bdir)
    assert meta["version"] == "gp-test-v1" and meta["location"] == "runtime" and meta["n_train"] == 100
    assert registry.load("gp-test-v1", model_dir=mdir, base_dir=bdir).n_train == 100
    with pytest.raises(FileNotFoundError):
        registry.load("tidak-ada", model_dir=mdir, base_dir=bdir)
