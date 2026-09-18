"""Fixture bersama test backend (PRD R22). Pemilik: David (B).

Setiap test otomatis mendapat `FP_RUNTIME_DIR` sementara di `var/test/<FP_MEMBER>/<uuid>/`
yang dihapus setelah test, dan `LLM_BASE_URL` yang mengarah ke port mati, sehingga tidak ada
test yang menyentuh DB, model, port instance, atau llama-server bersama.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

FP_HOME = Path(__file__).resolve().parents[2]
if str(FP_HOME) not in sys.path:
    sys.path.insert(0, str(FP_HOME))

DEAD_LLM_URL = "http://127.0.0.1:9/v1"


def pytest_configure(config: pytest.Config) -> None:
    member = os.environ.get("FP_MEMBER", "")
    if member not in {"marshal", "david", "dafa", "nico", "demo"}:
        raise pytest.UsageError(
            "FP_MEMBER belum di-set. Jalankan dulu: FP_MEMBER=<nama> source ~/work/formulapilot/scripts/env.sh"
        )


@pytest.fixture(scope="session")
def fp_home() -> Path:
    return FP_HOME


@pytest.fixture(scope="session")
def fixtures_dir(fp_home: Path) -> Path:
    return fp_home / "contracts" / "fixtures"


@pytest.fixture(autouse=True)
def runtime_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    member = os.environ["FP_MEMBER"]
    path = FP_HOME / "var" / "test" / member / uuid.uuid4().hex[:12]
    for sub in ("models", "logs", "run"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FP_HOME", str(FP_HOME))
    monkeypatch.setenv("FP_RUNTIME_DIR", str(path))
    monkeypatch.setenv("LLM_BASE_URL", DEAD_LLM_URL)
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("AGENT_WARMUP", "false")

    from fp import config

    config.get_settings(refresh=True)
    try:
        yield path
    finally:
        _release_blockers()
        logger = logging.getLogger("formulapilot")
        for h in list(logger.handlers):
            if str(getattr(h, "_fp_target", "")).startswith(str(path)):
                logger.removeHandler(h)
                h.close()
        monkeypatch.undo()
        config.get_settings(refresh=True)
        shutil.rmtree(path, ignore_errors=True)


# Test double untuk test backend milik David. Hanya dipakai di test; bukan implementasi pengganti (R23).

_BLOCKERS: list = []


def _release_blockers() -> None:
    while _BLOCKERS:
        _BLOCKERS.pop().set()


class FakeDesigner:
    is_stub = True
    version = "gp-global-v1"
    scope = "global"
    n_train = 400

    def __init__(self, fail: bool = False, block: bool = False, tie: bool = False) -> None:
        import threading

        self.fail = fail
        self.tie = tie
        self.release = threading.Event()
        if not block:
            self.release.set()
        else:
            _BLOCKERS.append(self.release)
        self.calls: list[dict] = []

    def fit(self, X, Y, prev=None):
        self.n_train = len(X)
        self.fit_parent = getattr(prev, "version", None)
        return self

    def save(self, path):
        from fp.io_utils import write_joblib

        write_joblib(path, {"version": self.version, "n_train": self.n_train})

    @classmethod
    def load(cls, path):
        from fp.io_utils import load_joblib

        data = load_joblib(path)
        d = cls()
        d.version, d.n_train = data["version"], data["n_train"]
        return d

    def p_specs(self, pool, specs):
        import pandas as pd

        frame = pool if hasattr(pool, "columns") else pd.DataFrame(list(pool))
        ok = (frame["NIACINAMIDE"] >= float(specs["NIACINAMIDE_MIN_PCT"])).astype(float)
        return pd.DataFrame({"P_TARGET": ok * 0.6})

    def rank_pool(self, pool, specs, n=3):
        """Bentuk keluaran sama dengan Designer Marshal: list (baris pool, prediksi bersarang)."""
        rows = pool.sort_values("NIACINAMIDE", ascending=False).head(n).to_dict(orient="records")
        self.calls.append({"rank_pool": list(pool.columns), "n": n})
        out = []
        for row in rows:
            ok = 1.0 if row["NIACINAMIDE"] >= specs["NIACINAMIDE_MIN_PCT"] else 0.0
            out.append((row, {
                "VISCOSITY_CP": 7777.0, "VISCOSITY_CP_CI95": (5000.0, 11000.0), "PH": 5.77, "PH_CI95": (5.5, 6.0),
                "D50_UM": 1.11, "D50_UM_CI95": (0.9, 1.4), "P_STABLE": 0.8, "COST_IDR_PER_KG": 30000.0, "UNCERTAINTY": 0.3,
                "P_SPECS": {"P_VISC": 0.9, "P_PH": 0.9, "P_D50": 0.9, "P_STABLE": 0.8, "DET_OK": ok}, "P_TARGET": 0.58 * ok,
            }))
        return out

    def propose(self, specs, n=3, seed=0, exclude=None, n_samples=30000):
        import pandas as pd

        self.calls.append({"specs": specs, "n": n, "seed": seed, "exclude": exclude})
        self.release.wait(timeout=20)
        if self.fail:
            raise RuntimeError("designer rusak (test)")
        niacin = [4.5, 5.0, 3.2, 6.0, 4.1]
        glycerin = [3.0, 0.0, 4.0, 2.0, 1.0]
        rows = []
        for i in range(n):
            f = {
                "GLYCERIN": glycerin[i], "NIACINAMIDE": niacin[i], "CETEARYL_ALCOHOL": 1.5, "EMULSIFIER": 2.5,
                "CCT": 5.0, "DIMETHICONE": 1.0, "XANTHAN": 0.3, "CARBOMER": 0.3, "NAOH": 0.5, "PHENOXYETHANOL": 0.8,
                "RPM": 7000.0, "HMIN": 5.0, "TEMP": 75.0,
            }
            f["AQUA"] = 100.0 - sum(v for k, v in f.items() if k not in ("RPM", "HMIN", "TEMP"))
            p_target = 0.95 if self.tie else round(0.6 - 0.1 * i, 3)
            cost = [33000.0, 31000.0, 35000.0, 32000.0, 34000.0][i] if self.tie else 28346.0
            rows.append({
                **f,
                "VISCOSITY_CP": 6450.0, "VISCOSITY_CP_LO": 3700.0, "VISCOSITY_CP_HI": 10900.0,
                "PH": 5.62, "PH_LO": 5.33, "PH_HI": 5.91,
                "D50_UM": 1.24, "D50_UM_LO": 0.83, "D50_UM_HI": 1.83,
                "P_STABLE": 0.84, "COST_IDR_PER_KG": cost, "UNCERTAINTY": 0.48,
                "P_VISC": 0.72, "P_PH": 0.97, "P_D50": 0.99, "DET_OK": 1.0 if f["NIACINAMIDE"] >= 4 else 0.0,
                "P_TARGET": p_target if f["NIACINAMIDE"] >= 4 else 0.0,
            })
        return pd.DataFrame(rows)


def _fake_guardian():
    import types
    from dataclasses import dataclass
    from typing import Any, Optional

    from fp.schemas import Gate, Issue

    @dataclass
    class GuardianContext:
        specs: dict
        bounds: Any = None
        regulatory: Any = None
        unc_max: Optional[float] = None
        train_X_scaled: Any = None
        scaler: Any = None
        nn_threshold: Optional[float] = None
        market: Any = None

    def check(formula, prediction, ctx):
        if formula["NIACINAMIDE"] < ctx.specs["NIACINAMIDE_MIN_PCT"]:
            return Gate(status="blocked", issues=[Issue(code="CLAIM_NOT_MET", severity="error", message="Kadar niacinamide di bawah klaim brief.", field="NIACINAMIDE")])
        if formula["GLYCERIN"] > 0:
            return {"status": "review", "issues": [{"code": "HALAL_SOURCE_CHECK", "severity": "warning", "message": "GLYCERIN: sumber perlu dicek (asumsi tim).", "field": "GLYCERIN"}]}
        return Gate(status="pass", issues=[])

    mod = types.ModuleType("fp.guardian")
    mod.GuardianContext = GuardianContext
    mod.check = check
    return mod


def _fake_market():
    import types

    mod = types.ModuleType("fp.market")
    mod.status = lambda: {"ready": True, "n_products": 1000, "built_at": "2026-09-17T18:00:00+07:00"}
    mod.support = lambda codes: {
        "type": "market", "codes": list(codes), "n_products_all": 14, "n_by_segment": {"skincare": 12, "makeup": 2, "suncare": 0},
        "n_indonesia": 1, "min_pair_support": 14, "weakest_pair": "CARBOMER|NIACINAMIDE",
        "examples": [{"product_name": "Produk uji", "brands": "Merek uji", "segment": "skincare"}],
    }
    mod.prevalence = lambda: {"NIACINAMIDE": 0.1}
    return mod


def _fake_scout():
    import types

    mod = types.ModuleType("fp.scout")
    mod.status = lambda: {"ready": True, "n_docs": 200, "built_at": "2026-09-17T18:00:00+07:00"}
    mod.query_for = lambda formula: "niacinamide carbomer gel stability"
    mod.search = lambda q, k=3: [
        {"type": "literature", "id": "1", "pmcid": "PMC1", "title": "Artikel uji satu", "year": 2021, "journal": "Jurnal uji", "url": "https://europepmc.org/", "score": 0.7, "snippet": "abstrak"},
        {"type": "literature", "id": "2", "pmcid": "PMC2", "title": "Artikel uji dua", "year": 2022, "journal": "Jurnal uji", "url": "https://europepmc.org/", "score": 0.6, "snippet": "abstrak"},
    ]
    return mod


@pytest.fixture()
def fake_agents(monkeypatch: pytest.MonkeyPatch) -> dict:
    mods = {"fp.guardian": _fake_guardian(), "fp.market": _fake_market(), "fp.scout": _fake_scout()}
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return mods


@pytest.fixture()
def api(runtime_dir: Path, fake_agents: dict):
    """TestClient dengan Designer palsu terpasang di scope global. `api.state` = AppState."""
    from fastapi.testclient import TestClient

    from backend.app.factory import create_app
    from fp.config import get_settings

    app = create_app(get_settings(refresh=True))
    with TestClient(app) as client:
        client.state = app.state.fp
        client.state.set_designer("global", "gp-global-v1", FakeDesigner())
        yield client


@pytest.fixture()
def lab_api(api, runtime_dir: Path, monkeypatch: pytest.MonkeyPatch):
    """`api` + fp.designer palsu, historical CSV sementara, dan gp-global-v1 terdaftar di DB instance test."""
    import types

    import pandas as pd

    from backend.app import repo
    from fp.schemas import FORMULA_FIELDS

    module = types.ModuleType("fp.designer")
    module.Designer = FakeDesigner
    monkeypatch.setitem(sys.modules, "fp.designer", module)

    rows = []
    for i in range(20):
        f = {k: 0.5 for k in FORMULA_FIELDS}
        f.update({"NIACINAMIDE": 2 + i * 0.3, "RPM": 5000.0, "HMIN": 3.0, "TEMP": 70.0})
        f["AQUA"] = 100.0 - sum(v for k, v in f.items() if k not in ("AQUA", "RPM", "HMIN", "TEMP"))
        rows.append({**f, "VISCOSITY_CP": 5000.0 + i, "PH": 5.5, "D50_UM": 1.5, "STABILITY_INDEX": 0.7})
    hist = runtime_dir / "historical_v1.csv"
    pd.DataFrame(rows).to_csv(hist, index=False)
    api.state.historical_path = hist

    base = runtime_dir / "base" / "gp-global-v1.joblib"
    FakeDesigner().save(base)
    repo.add_model_version(api.state.db, "gp-global-v1", "global", str(base), 400)
    api.state.set_designer("global", "gp-global-v1", FakeDesigner.load(base))
    return api


@pytest.fixture()
def replay_api(lab_api, runtime_dir: Path):
    """`lab_api` + historical 40 baris dengan record_id: H0001..H0030 tidak lolos (niacinamide 2%), H0031..H0040 lolos semua."""
    import pandas as pd

    from fp.schemas import FORMULA_FIELDS

    rows = []
    for i in range(40):
        hit = i >= 30
        f = {k: 0.5 for k in FORMULA_FIELDS}
        f.update({"NIACINAMIDE": 5.0 + i * 0.01 if hit else 2.0 + i * 0.01, "RPM": 5000.0, "HMIN": 3.0, "TEMP": 70.0})
        f["AQUA"] = 100.0 - sum(v for k, v in f.items() if k not in ("AQUA", "RPM", "HMIN", "TEMP"))
        rows.append({
            "record_id": f"H{i + 1:04d}", "source": "test", **f,
            "VISCOSITY_CP": 6123.45 + i, "PH": 5.61, "D50_UM": 1.23, "STABILITY_INDEX": 0.91, "STABLE": 1,
            "COST_IDR_PER_KG": 31234.5, "variant": "v1", "noise_seed": 1,
        })
    hist = runtime_dir / "historical_replay.csv"
    pd.DataFrame(rows).to_csv(hist, index=False)
    lab_api.state.historical_path = hist
    return lab_api


def wait_run(client, run_id: str, timeout: float = 15.0) -> dict:
    import time

    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/api/v1/runs/{run_id}").json()
        if body["data"]["status"] != "running" or time.monotonic() > deadline:
            return body["data"]
        time.sleep(0.05)
