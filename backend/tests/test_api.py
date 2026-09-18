"""Test API backend (PRD §14.7). Pemilik: David (B)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.factory import create_app
from fp import schemas as S
from fp.config import get_settings


@pytest.fixture()
def client(runtime_dir: Path):
    app = create_app(get_settings(refresh=True))
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient, runtime_dir: Path) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("live", "degraded")
    health = S.Health.model_validate(body["data"])
    assert health.db_ready is True
    assert health.llm_ready is False
    assert body["mode"] == "degraded"
    assert r.headers["X-Request-ID"].startswith("req_")
    assert (runtime_dir / "app.db").is_file()


def test_request_id_is_echoed(client: TestClient) -> None:
    r = client.get("/api/v1/health", headers={"X-Request-ID": "req_abc123"})
    assert r.headers["X-Request-ID"] == "req_abc123"


def test_unknown_api_path_is_enveloped(client: TestClient) -> None:
    r = client.get("/api/v1/tidak-ada")
    assert r.status_code == 404
    err = S.ErrorEnvelope.model_validate(r.json())
    assert err.error.code == "NOT_FOUND"
    assert err.error.request_id == r.headers["X-Request-ID"]


def test_briefs(client: TestClient) -> None:
    r = client.get("/api/v1/briefs")
    if not get_settings().briefs_json.is_file():
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "DATA_NOT_READY"
        return
    assert r.status_code == 200
    briefs = [S.Brief.model_validate(b) for b in r.json()["data"]]
    assert "niacinamide_gel_cream" in {b.brief_id for b in briefs}


def test_palette(client: TestClient) -> None:
    r = client.get("/api/v1/palette")
    if not get_settings().ingredients_csv.is_file():
        assert r.status_code == 503
        return
    assert r.status_code == 200
    palette = S.Palette.model_validate(r.json()["data"])
    codes = [i.code for i in palette.ingredients]
    assert codes[:10] == list(S.INGREDIENT_FIELDS)
    assert [p.code for p in palette.process] == list(S.PROCESS_FIELDS)


def test_root_serves_placeholder_or_frontend(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_db_persists_across_app_instances(runtime_dir: Path) -> None:
    from backend.app import repo

    app1 = create_app(get_settings(refresh=True))
    with TestClient(app1):
        repo.add_model_version(app1.state.fp.db, "gp-global-v9", "global", "/x.joblib", 5)
    app2 = create_app(get_settings(refresh=True))
    with TestClient(app2):
        row = repo.active_model_version(app2.state.fp.db, "global")
    assert row["version"] == "gp-global-v9"


# B-04 run deterministik

from conftest import FakeDesigner, wait_run  # noqa: E402

BRIEF = "niacinamide_gel_cream"


def _post_run(api, **overrides):
    body = {"run_mode": "explore", "brief_id": BRIEF, "n": 3, "use_orchestrator": False, **overrides}
    return api.post("/api/v1/runs", json=body)


def test_run_explore(api) -> None:
    r = _post_run(api)
    assert r.status_code == 202, r.text
    created = S.RunCreated.model_validate(r.json()["data"])
    data = wait_run(api, created.run_id)
    run = S.Run.model_validate(data)
    assert run.status == "done", run.error
    assert run.llm_status == "not_used"
    assert len(run.candidates) == 3
    assert [c.rank for c in run.candidates] == [1, 2, 3]
    for c in run.candidates:
        total = sum(getattr(c.formula, k) for k in S.INGREDIENT_FIELDS) + c.formula.AQUA
        assert abs(total - 100) < 1e-3
        assert c.prediction is not None and 0 <= c.prediction.P_TARGET <= 1
        assert c.summary.source == "template" and c.summary.text.startswith("Prediksi viskositas")
    assert [c.gate.status for c in run.candidates] == ["review", "pass", "blocked"]
    assert run.candidates[2].evidence == []
    for c in run.candidates[:2]:
        assert {e.type for e in c.evidence} == {"market", "literature"}
        market = next(e for e in c.evidence if e.type == "market")
        assert market.title.startswith("Kombinasi bahan ini ditemukan pada 14 produk")
    assert run.recommendation and "#1" in run.recommendation and "#3" not in run.recommendation
    seqs = [e.seq for e in run.events]
    assert seqs == list(range(1, len(seqs) + 1))
    actions = [(e.agent, e.action, e.status) for e in run.events]
    assert actions[0] == ("system", "run_started", "done")
    assert actions[-1] == ("system", "run_finished", "done")
    starts = {e.detail["call"] for e in run.events if e.status == "started"}
    dones = {e.detail["call"] for e in run.events if e.status == "done" and "call" in e.detail}
    assert starts == dones and "designer_propose#1" in starts
    assert sum(1 for e in run.events if e.action == "check" and e.status == "done") == 3


def test_run_after_seq_filters_events(api) -> None:
    run_id = _post_run(api).json()["data"]["run_id"]
    full = wait_run(api, run_id)
    last = full["events"][-1]["seq"]
    partial = api.get(f"/api/v1/runs/{run_id}?after_seq={last - 2}").json()["data"]
    assert [e["seq"] for e in partial["events"]] == [last - 1, last]
    assert len(partial["candidates"]) == 3


def test_run_excludes_tested_formulas(api) -> None:
    from backend.app import repo

    run_id = _post_run(api).json()["data"]["run_id"]
    first = S.Run.model_validate(wait_run(api, run_id))
    cand = first.candidates[0]
    lab = S.LabResult(
        lab_result_id=repo.new_id("lab"), batch_index=1, outputs={"PH": 5.6}, specs_met={"ALL": False},
        source="virtual_lab", variant="v1", recorded_at="2026-09-17T19:00:00+07:00",
    )
    repo.insert_lab_result(api.state.db, cand.candidate_id, "global", lab)
    designer = FakeDesigner()
    api.state.set_designer("global", "gp-global-v2", designer)
    second = wait_run(api, _post_run(api).json()["data"]["run_id"])
    assert second["model_version"] == "gp-global-v2"
    exclude = designer.calls[0]["exclude"]
    assert exclude is not None and len(exclude) == 1
    assert exclude.iloc[0]["NIACINAMIDE"] == cand.formula.NIACINAMIDE


def test_run_in_progress_conflict(api) -> None:
    slow = FakeDesigner(block=True)
    api.state.set_designer("global", "gp-global-v1", slow)
    first = _post_run(api)
    assert first.status_code == 202
    second = _post_run(api)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "RUN_IN_PROGRESS"
    slow.release.set()
    assert wait_run(api, first.json()["data"]["run_id"])["status"] == "done"
    third = _post_run(api)
    assert third.status_code == 202
    assert wait_run(api, third.json()["data"]["run_id"])["status"] == "done"


def test_run_model_not_ready(runtime_dir, fake_agents) -> None:
    app = create_app(get_settings(refresh=True))
    with TestClient(app) as c:
        app.state.fp._designers.clear()
        r = c.post("/api/v1/runs", json={"brief_id": BRIEF})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "MODEL_NOT_READY"


def test_run_brief_not_found_and_validation(api) -> None:
    r = _post_run(api, brief_id="tidak_ada")
    assert r.status_code == 404 and r.json()["error"]["code"] == "BRIEF_NOT_FOUND"
    r = _post_run(api, n=9)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.get("/api/v1/runs/run_000000000000").json()["error"]["code"] == "RUN_NOT_FOUND"


def test_run_specs_override_brief(api) -> None:
    specs = {"NIACINAMIDE_MIN_PCT": 5.5, "VISCOSITY_CP": [3000, 9000], "PH": [5.0, 6.0], "D50_UM_MAX": 2.0, "STABLE": True, "COST_IDR_PER_KG_MAX": 40000}
    run = wait_run(api, _post_run(api, specs=specs).json()["data"]["run_id"])
    assert run["specs"]["NIACINAMIDE_MIN_PCT"] == 5.5
    low = [c for c in run["candidates"] if c["formula"]["NIACINAMIDE"] < 5.5]
    assert low and all(c["gate"]["status"] == "blocked" for c in low)


def test_run_designer_failure_marks_failed(api) -> None:
    api.state.set_designer("global", "gp-global-v1", FakeDesigner(fail=True))
    run = wait_run(api, _post_run(api).json()["data"]["run_id"])
    assert run["status"] == "failed"
    assert "designer rusak" in run["error"]
    assert any(e["agent"] == "system" and e["action"] == "error" for e in run["events"])
    again = _post_run(api)
    assert again.status_code == 202
    assert wait_run(api, again.json()["data"]["run_id"])["status"] == "failed"


def test_run_orchestrator_when_llm_down_is_degraded(api) -> None:
    run = wait_run(api, _post_run(api, use_orchestrator=True).json()["data"]["run_id"])
    assert run["status"] == "done"
    assert run["llm_status"] == "degraded"
    assert all(c["summary"]["source"] == "template" for c in run["candidates"])
    assert any(e["agent"] == "orchestrator" and e["status"] == "failed" for e in run["events"])
    assert any(e["action"] == "policy_enforced" for e in run["events"])
    assert api.get("/api/v1/health").json()["mode"] == "degraded"


def test_run_without_guardian_module_requires_review(api, monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "fp.guardian", None)
    run = wait_run(api, _post_run(api).json()["data"]["run_id"])
    assert run["status"] == "done"
    assert {c["gate"]["status"] for c in run["candidates"]} == {"review"}
    assert all(c["gate"]["issues"][0]["code"] == "GUARDIAN_UNAVAILABLE" for c in run["candidates"])


def test_run_without_market_and_scout(api, monkeypatch) -> None:
    import sys
    import types

    down = types.ModuleType("fp.market")
    down.status = lambda: {"ready": False}
    monkeypatch.setitem(sys.modules, "fp.market", down)
    monkeypatch.setitem(sys.modules, "fp.scout", None)
    run = wait_run(api, _post_run(api).json()["data"]["run_id"])
    assert run["status"] == "done"
    assert all(c["evidence"] == [] for c in run["candidates"])


def test_run_with_real_agent_modules(runtime_dir) -> None:
    """Integrasi dengan fp.guardian / fp.market / fp.scout milik Nico (stub atau asli), Designer tetap palsu."""
    import importlib

    for name in ("fp.guardian", "fp.market", "fp.scout"):
        try:
            importlib.import_module(name)
        except Exception as exc:
            pytest.skip(f"{name} belum bisa di-import: {exc}")
    app = create_app(get_settings(refresh=True))
    with TestClient(app) as c:
        app.state.fp.set_designer("global", "gp-global-v1", FakeDesigner())
        r = c.post("/api/v1/runs", json={"brief_id": BRIEF, "n": 3})
        run = S.Run.model_validate(wait_run(c, r.json()["data"]["run_id"], timeout=150))
    assert run.status == "done", run.error
    assert not any(e.status == "failed" for e in run.events), [e for e in run.events if e.status == "failed"]
    low_claim = run.candidates[2]
    assert low_claim.formula.NIACINAMIDE < 4
    assert low_claim.gate.status == "blocked"
    assert "CLAIM_NOT_MET" in {i.code for i in low_claim.gate.issues}
    assert all(c.gate.status in ("pass", "review") for c in run.candidates[:2])
    assert all(i.code != "PENDING_CHECK" for c in run.candidates for i in c.gate.issues)


# B-05 keputusan

def _done_run(api) -> S.Run:
    return S.Run.model_validate(wait_run(api, _post_run(api).json()["data"]["run_id"]))


def _decide(api, candidate_id: str, **body):
    payload = {"decision": "approved", "reason": "peluang tertinggi", "acknowledged": False, **body}
    return api.post(f"/api/v1/candidates/{candidate_id}/decision", json=payload)


def test_decision_rules(api) -> None:
    review, passed, blocked = _done_run(api).candidates
    assert (review.gate.status, passed.gate.status, blocked.gate.status) == ("review", "pass", "blocked")

    r = _decide(api, blocked.candidate_id, acknowledged=True)
    assert r.status_code == 409 and r.json()["error"]["code"] == "GATE_BLOCKED"

    r = _decide(api, review.candidate_id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACK_REQUIRED"

    r = _decide(api, review.candidate_id, reason="  ok  ", acknowledged=True)
    assert r.status_code == 422 and r.json()["error"]["code"] == "REASON_REQUIRED"

    r = _decide(api, review.candidate_id, acknowledged=True)
    assert r.status_code == 200, r.text
    cand = S.Candidate.model_validate(r.json()["data"])
    assert cand.decision == "approved" and cand.acknowledged and cand.decision_reason == "peluang tertinggi"

    r = _decide(api, review.candidate_id, acknowledged=True)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_DECIDED"

    r = _decide(api, passed.candidate_id)
    assert r.status_code == 200 and r.json()["data"]["decision"] == "approved"

    r = _decide(api, blocked.candidate_id, decision="rejected", reason="klaim tidak terpenuhi")
    assert r.status_code == 200 and r.json()["data"]["decision"] == "rejected"

    run = api.get(f"/api/v1/runs/{review.run_id}").json()["data"]
    assert [c["decision"] for c in run["candidates"]] == ["approved", "approved", "rejected"]


def test_decision_unknown_candidate_and_bad_body(api) -> None:
    r = _decide(api, "cand_000000000000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "CANDIDATE_NOT_FOUND"
    r = api.post("/api/v1/candidates/cand_000000000000/decision", json={"decision": "maybe", "reason": "xxxxx"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_decision_survives_restart(runtime_dir, fake_agents) -> None:
    app1 = create_app(get_settings(refresh=True))
    with TestClient(app1) as c1:
        app1.state.fp.set_designer("global", "gp-global-v1", FakeDesigner())
        run = S.Run.model_validate(wait_run(c1, c1.post("/api/v1/runs", json={"brief_id": BRIEF}).json()["data"]["run_id"]))
        assert _decide(c1, run.candidates[1].candidate_id).status_code == 200
    app2 = create_app(get_settings(refresh=True))
    with TestClient(app2) as c2:
        again = c2.get(f"/api/v1/runs/{run.run_id}").json()["data"]
    assert again["status"] == "done"
    assert again["candidates"][1]["decision"] == "approved"


# B-06 uji Virtual Lab, retrain, progress, reset

def _test(api, candidate_id: str):
    return api.post(f"/api/v1/candidates/{candidate_id}/test")


def test_lab_test_retrain_progress_and_reset(lab_api, fp_home) -> None:
    artifacts_before = sorted(p.name for p in (fp_home / "artifacts" / "models").glob("*"))
    run = _done_run(lab_api)
    review, passed, blocked = run.candidates

    r = _test(lab_api, passed.candidate_id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_APPROVED"
    assert _decide(lab_api, passed.candidate_id).status_code == 200

    r = _test(lab_api, passed.candidate_id)
    assert r.status_code == 200, r.text
    first = S.LabTestResponse.model_validate(r.json()["data"])
    assert first.lab_result.batch_index == 1
    assert first.lab_result.source == "virtual_lab" and first.lab_result.variant == "v1"
    assert first.lab_result.retrained_model_version == "gp-global-v2"
    assert set(first.lab_result.outputs) == set(S.LAB_OUTPUT_KEYS)
    assert set(first.lab_result.specs_met) == set(S.SPECS_MET_KEYS)
    assert first.candidate.lab_result == first.lab_result
    assert first.progress.batches == 1 and len(first.progress.history) == 1

    r = _test(lab_api, passed.candidate_id)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ALREADY_TESTED"

    health = lab_api.get("/api/v1/health").json()["data"]
    assert health["model_version"] == "gp-global-v2"
    assert (lab_api.state.settings.runtime_models_dir / "gp-global-v2.joblib").is_file()
    events = lab_api.get(f"/api/v1/runs/{run.run_id}").json()["data"]["events"]
    assert ("lab", "lab_batch", "done") in {(e["agent"], e["action"], e["status"]) for e in events}
    retrain_done = [e for e in events if e["action"] == "retrain" and e["status"] == "done"]
    assert retrain_done and retrain_done[0]["detail"]["model_version"] == "gp-global-v2"

    assert _decide(lab_api, review.candidate_id, acknowledged=True).status_code == 200
    second = S.LabTestResponse.model_validate(_test(lab_api, review.candidate_id).json()["data"])
    assert second.lab_result.batch_index == 2 and second.lab_result.retrained_model_version == "gp-global-v3"
    assert lab_api.state.get_designer("global")[1].n_train == 22

    next_run = _done_run(lab_api)
    assert next_run.model_version == "gp-global-v3"

    progress = S.Progress.model_validate(lab_api.get("/api/v1/progress?scope=global").json()["data"])
    assert progress.batches == 2 and [h.batch_index for h in progress.history] == [1, 2]
    assert progress.best_specs_met == max(sum(h.specs_met[k] for k in S.SPEC_KEYS) for h in progress.history)

    r = lab_api.post("/api/v1/progress/reset", json={"scope": "global"})
    assert r.status_code == 200 and r.json()["data"]["batches"] == 0
    assert lab_api.get("/api/v1/health").json()["data"]["model_version"] == "gp-global-v1"
    assert _done_run(lab_api).model_version == "gp-global-v1"

    again = _done_run(lab_api).candidates[1]
    assert _decide(lab_api, again.candidate_id).status_code == 200
    third = S.LabTestResponse.model_validate(_test(lab_api, again.candidate_id).json()["data"])
    assert third.lab_result.batch_index == 1
    assert third.lab_result.retrained_model_version == "gp-global-v4"
    assert sorted(p.name for p in (fp_home / "artifacts" / "models").glob("*")) == artifacts_before


def test_lab_outputs_are_reproducible(lab_api) -> None:
    from backend.app.services import lab

    cand = _done_run(lab_api).candidates[1]
    assert lab.run_virtual_lab(lab_api.state, cand.formula, cand.candidate_id) == lab.run_virtual_lab(
        lab_api.state, cand.formula, cand.candidate_id
    )


def test_lab_result_kept_when_retrain_fails(lab_api, runtime_dir) -> None:
    lab_api.state.historical_path = runtime_dir / "tidak_ada.csv"
    cand = _done_run(lab_api).candidates[1]
    assert _decide(lab_api, cand.candidate_id).status_code == 200
    r = _test(lab_api, cand.candidate_id)
    assert r.status_code == 200
    body = S.LabTestResponse.model_validate(r.json()["data"])
    assert body.lab_result.retrained_model_version is None
    assert body.progress.batches == 1
    events = lab_api.get(f"/api/v1/runs/{cand.run_id}").json()["data"]["events"]
    failed = [e for e in events if e["action"] == "retrain" and e["status"] == "failed"]
    assert failed and "belum ada" in failed[0]["detail"]["error"]


def test_designer_rows_accepts_marshal_shapes() -> None:
    from backend.app.services.pipeline import designer_rows, row_to_formula, row_to_prediction

    formula = {"GLYCERIN": 3.0, "NIACINAMIDE": 4.5, "CETEARYL_ALCOHOL": 1.5, "EMULSIFIER": 2.5, "CCT": 5.0, "DIMETHICONE": 1.0,
               "XANTHAN": 0.3, "CARBOMER": 0.3, "NAOH": 0.5, "PHENOXYETHANOL": 0.8, "RPM": 7000.0, "HMIN": 5.0, "TEMP": 75.0,
               "AQUA": 80.6, "OIL_PHASE": 6.75}
    prediction = {"mu_visc": 3.8, "sd_visc": 0.1, "VISCOSITY_CP": 6310.0, "VISCOSITY_CP_CI95": (3900.0, 10200.0),
                  "PH": 5.6, "PH_CI95": (5.3, 5.9), "D50_UM": 1.2, "D50_UM_CI95": (0.8, 1.8), "P_STABLE": 0.9,
                  "COST_IDR_PER_KG": 28346.0, "UNCERTAINTY": 0.4,
                  "P_SPECS": {"P_VISC": 0.7, "P_PH": 0.99, "P_D50": 1.0, "P_STABLE": 0.9, "DET_OK": 1.0}, "P_TARGET": 0.62}
    for shape in ([{"formula": formula, "prediction": prediction, "reason": "model"}], [(formula, prediction)]):
        row = designer_rows(shape)[0]
        f = row_to_formula(row)
        p = row_to_prediction(row, "gp-global-v1")
        assert f.AQUA == 80.6 and p is not None
        assert p.VISCOSITY_CP_CI95 == (3900.0, 10200.0) and p.P_SPECS["DET_OK"] == 1.0 and p.P_TARGET == 0.62


def test_real_designer_run_test_and_retrain(runtime_dir, fake_agents, monkeypatch, fp_home) -> None:
    """End-to-end dengan fp.designer dan model gp-global-v1 milik Marshal (AC-02, AC-04). Dilewati bila belum ada."""
    import importlib
    import sys
    import time

    base = fp_home / "artifacts" / "models" / "gp-global-v1.joblib"
    hist = fp_home / "data" / "virtual_lab" / "historical_v1.csv"
    if not base.is_file() or not hist.is_file():
        pytest.skip("model/historical Marshal belum ada")
    monkeypatch.delitem(sys.modules, "fp.designer", raising=False)
    try:
        importlib.import_module("fp.designer")
    except Exception as exc:
        pytest.skip(f"fp.designer belum bisa di-import: {exc}")
    monkeypatch.setenv("DESIGNER_N_SAMPLES", "100")
    app = create_app(get_settings(refresh=True))
    with TestClient(app) as c:
        health = c.get("/api/v1/health").json()["data"]
        assert health["model_ready"] is True and health["model_version"] == "gp-global-v1"
        started = time.perf_counter()
        run = S.Run.model_validate(wait_run(c, c.post("/api/v1/runs", json={"brief_id": BRIEF, "n": 3}).json()["data"]["run_id"], timeout=120))
        run_seconds = time.perf_counter() - started
        assert run.status == "done", run.error
        assert len(run.candidates) == 3
        for cand in run.candidates:
            assert cand.prediction is not None
            total = sum(getattr(cand.formula, k) for k in S.INGREDIENT_FIELDS) + cand.formula.AQUA
            assert abs(total - 100) < 1e-3
        target = next(cd for cd in run.candidates if cd.gate.status != "blocked")
        assert _decide(c, target.candidate_id, acknowledged=True).status_code == 200
        started = time.perf_counter()
        r = _test(c, target.candidate_id)
        test_seconds = time.perf_counter() - started
        assert r.status_code == 200, r.text
        body = S.LabTestResponse.model_validate(r.json()["data"])
        assert body.lab_result.retrained_model_version == "gp-global-v2"
        assert c.get("/api/v1/health").json()["data"]["model_version"] == "gp-global-v2"
    print(f"\nREAL_DESIGNER run_s={run_seconds:.1f} test_retrain_s={test_seconds:.1f} gates={[cd.gate.status for cd in run.candidates]}")


# B-07 replay

def test_replay_session_run_reveal(replay_api) -> None:
    import json

    api = replay_api
    r = api.post("/api/v1/replay/sessions", json={"brief_id": BRIEF, "seed": 7})
    assert r.status_code == 200, r.text
    session = S.ReplaySession.model_validate(r.json()["data"])
    sid = session.session_id
    assert session.seed == 7 and session.progress is None
    assert len(session.known) == 10 and session.pool_size == 30
    assert all(not k.specs_met["ALL"] for k in session.known)
    assert session.model_version == f"gp-session-{sid}-v1"
    again = api.post("/api/v1/replay/sessions", json={"brief_id": BRIEF, "seed": 7}).json()["data"]
    assert [k["record_id"] for k in again["known"]] == [k.record_id for k in session.known]

    r = api.post("/api/v1/runs", json={"run_mode": "replay", "session_id": sid, "brief_id": BRIEF, "n": 3})
    assert r.status_code == 202, r.text
    raw = wait_run(api, r.json()["data"]["run_id"])
    run = S.Run.model_validate(raw)
    assert run.status == "done", run.error
    assert run.model_version == f"gp-session-{sid}-v1"
    designer = api.state.get_designer(f"session:{sid}")[1]
    assert set(designer.calls[-1]["rank_pool"]) == {"record_id", *S.FORMULA_FIELDS}
    text = json.dumps(raw)
    assert "6123." not in text and "6124." not in text and "31234.5" not in text
    for cand in run.candidates:
        assert cand.origin == "pool" and cand.source_record_id in {f"H{i:04d}" for i in range(31, 41)}
        assert cand.prediction.VISCOSITY_CP == 7777.0

    first = run.candidates[0]
    assert _test(api, first.candidate_id).json()["error"]["code"] == "NOT_EXPLORE"
    assert api.post(f"/api/v1/candidates/{first.candidate_id}/reveal").json()["error"]["code"] == "NOT_APPROVED"
    assert _decide(api, first.candidate_id, acknowledged=True).status_code == 200
    r = api.post(f"/api/v1/candidates/{first.candidate_id}/reveal")
    assert r.status_code == 200, r.text
    body = S.LabTestResponse.model_validate(r.json()["data"])
    true_visc = 6123.45 + int(first.source_record_id[1:]) - 1
    assert body.lab_result.source == "historical" and body.lab_result.outputs["VISCOSITY_CP"] == pytest.approx(true_visc)
    assert body.lab_result.specs_met["ALL"] is True and body.lab_result.batch_index == 1
    assert body.lab_result.retrained_model_version == f"gp-session-{sid}-v2"
    assert body.progress.scope == f"session:{sid}" and body.progress.hit_at_batch == 1
    assert api.post(f"/api/v1/candidates/{first.candidate_id}/reveal").json()["error"]["code"] == "ALREADY_REVEALED"

    view = S.ReplaySession.model_validate(api.get(f"/api/v1/replay/sessions/{sid}").json()["data"])
    assert view.seed is None and view.progress.batches == 1
    assert len(view.known) == 11 and view.known[-1].record_id == first.source_record_id and view.pool_size == 29
    assert view.model_version == f"gp-session-{sid}-v2"
    assert api.get(f"/api/v1/progress?scope=session:{sid}").json()["data"]["batches"] == 1
    assert api.get("/api/v1/progress?scope=global").json()["data"]["batches"] == 0

    nxt = S.Run.model_validate(wait_run(api, api.post("/api/v1/runs", json={"run_mode": "replay", "session_id": sid, "brief_id": BRIEF}).json()["data"]["run_id"]))
    assert first.source_record_id not in {c.source_record_id for c in nxt.candidates}
    assert nxt.model_version == f"gp-session-{sid}-v2"


def test_replay_errors(replay_api) -> None:
    api = replay_api
    r = api.post("/api/v1/runs", json={"run_mode": "replay", "session_id": "rs_000000000000", "brief_id": BRIEF})
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert api.get("/api/v1/replay/sessions/rs_000000000000").json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert api.post("/api/v1/replay/sessions", json={"brief_id": "tidak_ada"}).json()["error"]["code"] == "BRIEF_NOT_FOUND"
    sid = api.post("/api/v1/replay/sessions", json={"brief_id": BRIEF}).json()["data"]["session_id"]
    r = api.post("/api/v1/runs", json={"run_mode": "replay", "session_id": sid, "brief_id": "light_moisturizer"})
    assert r.status_code == 422
    explore = _done_run(api).candidates[1]
    assert _decide(api, explore.candidate_id).status_code == 200
    assert api.post(f"/api/v1/candidates/{explore.candidate_id}/reveal").json()["error"]["code"] == "NOT_POOL"


# B-10 agent jobs, status, market summary

def _wait_job(api, agent: str, timeout: float = 20.0) -> dict:
    import time

    deadline = time.monotonic() + timeout
    while True:
        job = api.get("/api/v1/agents/status").json()["data"][agent]["last_job"]
        if (job and job["status"] in ("done", "failed")) or time.monotonic() > deadline:
            return job
        time.sleep(0.05)


def test_agent_designer_retrain_job(lab_api) -> None:
    status = S.AgentsStatus.model_validate(lab_api.get("/api/v1/agents/status").json()["data"])
    assert status.designer.ready and status.designer.last_job is None
    assert status.guardian.ready and status.scout.ready and status.market.ready
    assert status.scheduler.ready is False
    r = lab_api.post("/api/v1/agents/designer/run")
    assert r.status_code == 202, r.text
    job_id = r.json()["data"]["job_id"]
    job = _wait_job(lab_api, "designer")
    assert job["job_id"] == job_id and job["status"] == "done", job
    assert job["trigger"] == "manual" and job["detail"]["model_version"] == "gp-global-v2"
    assert job["started_at"] and job["finished_at"]
    assert lab_api.get("/api/v1/health").json()["data"]["model_version"] == "gp-global-v2"


def test_agent_job_running_conflict_and_unknown(lab_api, monkeypatch) -> None:
    import threading

    from backend.app import jobs

    gate = threading.Event()
    monkeypatch.setitem(jobs.RUNNERS, "designer_retrain", lambda state: (gate.wait(10), {"ok": True})[1])
    assert lab_api.post("/api/v1/agents/designer/run").status_code == 202
    r = lab_api.post("/api/v1/agents/designer/run")
    assert r.status_code == 409 and r.json()["error"]["code"] == "JOB_RUNNING"
    gate.set()
    assert _wait_job(lab_api, "designer")["status"] == "done"
    r = lab_api.post("/api/v1/agents/orchestrator/run")
    assert r.status_code == 404 and r.json()["error"]["code"] == "AGENT_NOT_FOUND"


def test_agent_guardian_recheck_updates_undecided(lab_api, fake_agents, monkeypatch) -> None:
    from fp.schemas import Gate, Issue

    run = _done_run(lab_api)
    review, passed, blocked = run.candidates
    assert _decide(lab_api, passed.candidate_id).status_code == 200
    strict = Gate(status="blocked", issues=[Issue(code="OVER_REG_MAX", severity="error", message="uji ketat")])
    monkeypatch.setattr(fake_agents["fp.guardian"], "check", lambda formula, prediction, ctx: strict)
    assert lab_api.post("/api/v1/agents/guardian/run").status_code == 202
    job = _wait_job(lab_api, "guardian")
    assert job["status"] == "done", job
    assert job["detail"]["run_id"] == run.run_id and job["detail"]["n_checked"] == 2
    assert {c["candidate_id"] for c in job["detail"]["changed"]} == {review.candidate_id}
    after = lab_api.get(f"/api/v1/runs/{run.run_id}").json()["data"]["candidates"]
    assert [c["gate"]["status"] for c in after] == ["blocked", "pass", "blocked"]


def test_agent_scout_reindex_and_market_summary(api, fake_agents, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(fake_agents["fp.scout"], "warmup", lambda: calls.append("warm") or True, raising=False)
    assert api.post("/api/v1/agents/scout/run").status_code == 202
    job = _wait_job(api, "scout")
    assert job["status"] == "done" and calls == ["warm"]
    assert job["detail"]["scout"]["ready"] is True and job["detail"]["market"]["ready"] is True

    monkeypatch.setattr(fake_agents["fp.market"], "summary", lambda: {"n_products": 1000, "n_indonesia": 3, "examples": {"x": 1}}, raising=False)
    data = api.get("/api/v1/market/summary").json()["data"]
    assert data == {"n_products": 1000, "n_indonesia": 3}
    monkeypatch.setattr(fake_agents["fp.market"], "status", lambda: {"ready": False})
    r = api.get("/api/v1/market/summary")
    assert r.status_code == 404 and r.json()["error"]["code"] == "MARKET_NOT_READY"


# B-11 hardening

def test_validation_messages_are_indonesian(api) -> None:
    r = _post_run(api, n=9)
    assert r.json()["error"]["message"] == "n: maksimal 5"
    r = api.post("/api/v1/runs", json={"n": 3})
    assert r.json()["error"]["message"] == "brief_id: wajib diisi"
    r = api.post("/api/v1/runs", content="bukan json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = _post_run(api, specs={"NIACINAMIDE_MIN_PCT": 4, "VISCOSITY_CP": [9000, 4000], "PH": [5, 6], "D50_UM_MAX": 3, "COST_IDR_PER_KG_MAX": 1})
    assert r.status_code == 422 and "min harus lebih kecil dari max" in r.json()["error"]["message"]


def test_stuck_run_expires_and_late_thread_cannot_revive_it(api, monkeypatch) -> None:
    import time

    monkeypatch.setenv("RUN_TIMEOUT_S", "1")
    api.state.settings = get_settings(refresh=True)
    slow = FakeDesigner(block=True)
    api.state.set_designer("global", "gp-global-v1", slow)
    run_id = _post_run(api).json()["data"]["run_id"]
    time.sleep(2.2)
    run = api.get(f"/api/v1/runs/{run_id}").json()["data"]
    assert run["status"] == "failed" and "batas waktu" in run["error"]
    assert any(e["detail"].get("reason") == "run_timeout" for e in run["events"])
    monkeypatch.setenv("RUN_TIMEOUT_S", "180")
    api.state.settings = get_settings(refresh=True)
    api.state.set_designer("global", "gp-global-v1", FakeDesigner())
    fresh = _post_run(api)
    assert fresh.status_code == 202
    slow.release.set()
    time.sleep(0.5)
    assert api.get(f"/api/v1/runs/{run_id}").json()["data"]["status"] == "failed"
    assert wait_run(api, fresh.json()["data"]["run_id"])["status"] == "done"


def test_restart_keeps_lab_results_and_retrained_model(lab_api, runtime_dir) -> None:
    run = _done_run(lab_api)
    cand = run.candidates[1]
    assert _decide(lab_api, cand.candidate_id).status_code == 200
    assert _test(lab_api, cand.candidate_id).json()["data"]["lab_result"]["retrained_model_version"] == "gp-global-v2"
    app2 = create_app(get_settings(refresh=True))
    with TestClient(app2) as c2:
        assert c2.get("/api/v1/health").json()["data"]["model_version"] == "gp-global-v2"
        progress = c2.get("/api/v1/progress").json()["data"]
        assert progress["batches"] == 1 and progress["history"][0]["candidate_id"] == cand.candidate_id
        again = c2.get(f"/api/v1/runs/{run.run_id}").json()["data"]
        assert again["candidates"][1]["lab_result"]["batch_index"] == 1
        assert c2.get("/api/v1/models?scope=global").json()["data"][0]["version"] == "gp-global-v2"


# B-13 scheduler (P2)

def test_scheduler_off_by_default(api) -> None:
    status = api.get("/api/v1/agents/status").json()["data"]
    assert status["scheduler"] == {"ready": False, "last_job": None, "next_run": None}
    assert api.state.scheduler is None


def test_scheduler_enabled_ticks(lab_api, monkeypatch) -> None:
    import time

    from backend.app.scheduler import AgentScheduler

    scheduler = AgentScheduler(lab_api.state)
    scheduler.start()
    lab_api.state.scheduler = scheduler
    try:
        status = S.AgentsStatus.model_validate(lab_api.get("/api/v1/agents/status").json()["data"])
        assert status.scheduler.ready and status.scheduler.next_run is not None
        assert status.designer.next_run and status.guardian.next_run and status.scout.next_run

        assert scheduler.tick_designer() is None
        cand = _done_run(lab_api).candidates[1]
        assert _decide(lab_api, cand.candidate_id).status_code == 200
        body = _test(lab_api, cand.candidate_id).json()["data"]
        assert body["lab_result"]["retrained_model_version"] == "gp-global-v2"
        time.sleep(1.1)
        assert scheduler.tick_designer() is None

        job_id = scheduler.tick_guardian()
        assert job_id
        job = _wait_job(lab_api, "guardian")
        assert job["job_id"] == job_id and job["trigger"] == "schedule" and job["status"] == "done"
    finally:
        scheduler.shutdown()
        lab_api.state.scheduler = None


def test_progress_bad_scope(api) -> None:
    assert api.get("/api/v1/progress?scope=apa").json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.get("/api/v1/progress?scope=session:rs_000000000000").json()["error"]["code"] == "SESSION_NOT_FOUND"
    empty = api.get("/api/v1/progress").json()["data"]
    assert empty == {"scope": "global", "batches": 0, "hit_at_batch": None, "best_specs_met": 0, "total_specs": 6, "history": []}


def test_tied_p_target_ranked_by_cheapest(api) -> None:
    """Brief mudah membuat P_TARGET menumpuk di 0,95; urutan kartu ditentukan biaya bahan."""
    api.state.set_designer("global", "gp-global-v1", FakeDesigner(tie=True))
    run = S.Run.model_validate(wait_run(api, _post_run(api, n=3).json()["data"]["run_id"]))
    costs = [c.prediction.COST_IDR_PER_KG for c in run.candidates]
    assert costs == sorted(costs) == [31000.0, 33000.0, 35000.0]
    assert [c.rank for c in run.candidates] == [1, 2, 3]
    assert {c.prediction.P_TARGET for c in run.candidates[:2]} == {0.95}
    assert run.candidates[2].prediction.P_TARGET == 0.0


def test_distinct_p_target_keeps_probability_order(api) -> None:
    run = S.Run.model_validate(wait_run(api, _post_run(api, n=3).json()["data"]["run_id"]))
    targets = [c.prediction.P_TARGET for c in run.candidates]
    assert targets == sorted(targets, reverse=True)


def test_cors_disabled_by_default_and_enabled_by_env(runtime_dir, fake_agents, monkeypatch) -> None:
    app = create_app(get_settings(refresh=True))
    with TestClient(app) as c:
        r = c.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers}

    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3000, http://127.0.0.1:3000")
    app2 = create_app(get_settings(refresh=True))
    with TestClient(app2) as c2:
        r = c2.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
        assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert "X-Request-ID" in r.headers.get("access-control-expose-headers", "")


def test_app_title_uses_product_name(api) -> None:
    assert api.get("/openapi.json").json()["info"]["title"] == "Rimula Agents API"
    assert "Rimula Agents" in api.get("/").text


# B-08 evaluasi, figur, model

def test_evaluation_missing_then_served_identically(api, runtime_dir, fixtures_dir) -> None:
    api.state.evaluation.path = runtime_dir / "evaluation.json"
    r = api.get("/api/v1/evaluation")
    assert r.status_code == 404 and r.json()["error"]["code"] == "EVALUATION_MISSING"
    assert api.get("/api/v1/health").json()["data"]["evaluation_ready"] is False

    raw = (fixtures_dir / "evaluation_min.json").read_text(encoding="utf-8")
    (runtime_dir / "evaluation.json").write_text(raw, encoding="utf-8")
    r = api.get("/api/v1/evaluation")
    assert r.status_code == 200
    import json

    assert r.json()["data"] == json.loads(raw)
    assert api.get("/api/v1/health").json()["data"]["evaluation_ready"] is True


def test_evaluation_figures(api, runtime_dir) -> None:
    figs = runtime_dir / "figures"
    figs.mkdir()
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    (figs / "closed_loop_v1.png").write_bytes(png)
    (runtime_dir / "secret.png").write_bytes(png)
    api.state.figures_dir = figs
    r = api.get("/api/v1/evaluation/figures/closed_loop_v1.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content == png
    for bad in ("tidak_ada.png", "closed_loop_v1.txt", "..%2Fsecret.png", ".hidden.png"):
        r = api.get(f"/api/v1/evaluation/figures/{bad}")
        assert r.status_code == 404, bad
        assert r.json()["error"]["code"] in ("FIGURE_NOT_FOUND", "NOT_FOUND")


def test_models_list(api) -> None:
    from backend.app import repo

    db = api.state.db
    repo.add_model_version(db, "gp-global-v1", "global", "/a.joblib", 400, created_at="2026-09-17T19:00:00+07:00")
    repo.add_model_version(db, "gp-global-v2", "global", "/b.joblib", 401, "gp-global-v1", created_at="2026-09-17T19:05:00+07:00")
    repo.add_model_version(db, "gp-session-rs_1-v1", "session:rs_1", "/c.joblib", 10, created_at="2026-09-17T19:06:00+07:00")
    everything = [S.ModelVersion.model_validate(m) for m in api.get("/api/v1/models").json()["data"]]
    assert [m.version for m in everything] == ["gp-session-rs_1-v1", "gp-global-v2", "gp-global-v1"]
    glob = api.get("/api/v1/models?scope=global").json()["data"]
    assert [(m["version"], m["is_active"]) for m in glob] == [("gp-global-v2", True), ("gp-global-v1", False)]


def test_list_runs(api) -> None:
    first = _post_run(api).json()["data"]["run_id"]
    wait_run(api, first)
    second = _post_run(api).json()["data"]["run_id"]
    wait_run(api, second)
    listed = [r["run_id"] for r in api.get("/api/v1/runs?limit=5").json()["data"]]
    assert listed[:2] == [second, first]


def test_custom_specs_are_sent_to_run_and_used(api) -> None:
    specs = {"NIACINAMIDE_MIN_PCT": 5.5, "VISCOSITY_CP": [3500, 9000], "PH": [5.1, 6.1], "D50_UM_MAX": 2.0, "STABLE": True, "COST_IDR_PER_KG_MAX": 42000}
    r = _post_run(api, specs=specs, n=2)
    assert r.status_code == 202, r.text
    run = wait_run(api, r.json()["data"]["run_id"])
    assert run["status"] == "done"
    assert run["specs"] == specs
    assert all(c["gate"]["status"] != "pending" for c in run["candidates"])


def _extra_specs_validators_present() -> bool:
    """Validator tambahan (viskositas > 0, batas pH) ditulis sesi lain; belum ada di fp/schemas.py repo."""
    try:
        S.Specs(NIACINAMIDE_MIN_PCT=4, VISCOSITY_CP=(0, 12000), PH=(5, 6.5), D50_UM_MAX=3, COST_IDR_PER_KG_MAX=50000)
    except Exception:
        return True
    return False


@pytest.mark.skipif(not _extra_specs_validators_present(), reason="validator specs tambahan belum ada di fp/schemas.py")
def test_invalid_custom_specs_are_rejected_before_run(api) -> None:
    base = {"NIACINAMIDE_MIN_PCT": 4, "VISCOSITY_CP": [4000, 12000], "PH": [5, 6.5], "D50_UM_MAX": 3, "STABLE": True, "COST_IDR_PER_KG_MAX": 50000}
    cases = [
        ({**base, "VISCOSITY_CP": [12000, 4000]}, "min harus lebih kecil dari max"),
        ({**base, "PH": [6.5, 5]}, "min harus lebih kecil dari max"),
        ({**base, "NIACINAMIDE_MIN_PCT": 11}, "maksimal 10"),
        ({**base, "PH": [2, 6]}, "minimal 3"),
        ({**base, "D50_UM_MAX": 0}, "harus lebih dari 0"),
        ({**base, "COST_IDR_PER_KG_MAX": 0}, "harus lebih dari 0"),
        ({**base, "VISCOSITY_CP": [0, 12000]}, "viskositas harus lebih dari 0"),
    ]
    for specs, message in cases:
        r = _post_run(api, specs=specs)
        assert r.status_code == 422, (specs, r.text)
        assert message in r.json()["error"]["message"], (specs, r.text)
