"""Test evaluasi (PRD §10, §17.1). Pemilik: Marshal (A); ditulis Nico saat ambil alih.

Versi mini dari `--quick` (1 seed, batch & langkah dibatasi, CV 60 baris) agar test < 2 menit.
Output ditulis ke var/test/<nama>/ (R22), bukan artifacts/.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from fp import evaluate, strategies
from fp.io_utils import read_json
from fp.schemas import EvaluationReport


def test_mini_run_schema_and_figures(runtime_dir):
    out = runtime_dir / "evaluation.json"
    figdir = runtime_dir / "figures"
    report = evaluate.run(
        quick=True, out=out, figdir=figdir, jobs=1, seeds=1, max_batches=3, replay_steps=3, lipo_steps=2,
        n_samples=300, cv_rows=60, hit_rate_samples=50,
    )
    saved = read_json(out)
    EvaluationReport.model_validate(saved)
    assert saved["quick"] is True and saved["brief_id"] == "niacinamide_gel_cream"
    for key in ("visc", "ph", "d50", "stab"):
        assert key in saved["cv"]
    assert 0 <= saved["cv"]["visc"]["coverage95"] <= 1
    assert saved["unc_max"] is not None and saved["unc_max"] > 0
    v1 = saved["closed_loop"]["results"]["v1"]
    assert set(v1) >= {"ai", "random", "heuristic", "curve"} and len(v1["curve"]) == 3
    assert saved["closed_loop"]["results"]["v2"] == {}
    assert set(saved["replay_historical"]) >= {"ai", "random", "heuristic", "max_steps", "seeds"}
    assert saved["savings_estimate"]["label"] == "simulasi"
    assert saved["runtime_seconds"] is not None
    for name in report["figures"]:
        assert (figdir / name).stat().st_size > 1000
    assert {"closed_loop_v1.png", "closed_loop_variants.png", "replay_historical.png", "cv_parity.png"} <= set(report["figures"])


def test_summarize_and_curve():
    s = evaluate.summarize([2, None, 4, 6], max_steps=40)
    assert s["median"] == 5.0 and s["found_rate"] == 0.75 and s["n_found"] == 3
    c = evaluate.curve({"ai": [2, None], "random": [None, None]}, max_steps=3)
    assert c[0] == {"batch": 1, "ai": 0.0, "random": 0.0} and c[1]["ai"] == 0.5


def test_select_initial_has_no_hits(fp_home):
    hist = pd.read_csv(fp_home / "data" / "virtual_lab" / "historical_v1.csv")
    specs = evaluate.load_specs()
    init = strategies.select_initial(hist, specs, k=10, seed=3)
    assert len(init) == 10 and not strategies.hit_mask(init, specs).any()
    f = strategies.record_to_formula(init.iloc[0])
    assert abs(sum(f.values()) - f["RPM"] - f["HMIN"] - f["TEMP"] - 100.0) < 1e-6
    assert strategies.select_initial(hist, specs, k=10, seed=3)["record_id"].tolist() == init["record_id"].tolist()


def test_heuristic_changes_one_variable(fp_home):
    hist = pd.read_csv(fp_home / "data" / "virtual_lab" / "historical_v1.csv").head(20)
    specs = evaluate.load_specs()
    base = strategies.record_to_formula(strategies.best_known(hist, specs))
    new = strategies.choose_heuristic(hist, specs, np.random.RandomState(0))
    changed = [k for k in base if k != "AQUA" and abs(base[k] - new[k]) > 1e-9]
    assert len(changed) == 1
