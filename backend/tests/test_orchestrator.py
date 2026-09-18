"""Test orchestrator (PRD §13, §14.7). LLM di-mock; test live opsional dengan FP_LIVE_LLM=1. Pemilik: David (B)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from backend.app.factory import create_app
from fp import schemas as S
from fp.config import get_settings
from fp.orchestrator import loop as orch
from fp.orchestrator.tools import TOOL_DEFINITIONS, execute_tool
from fp.orchestrator.validate import check_claims, collect_numbers, validate_text

from conftest import FakeDesigner, wait_run

BRIEF = "niacinamide_gel_cream"


# LLM palsu -------------------------------------------------------------------

def _call(name: str, args: Any, i: int) -> SimpleNamespace:
    raw = args if isinstance(args, str) else json.dumps(args)
    return SimpleNamespace(id=f"call_{i}", type="function", function=SimpleNamespace(name=name, arguments=raw))


def _reply(content: Optional[str] = None, calls: Optional[list] = None) -> SimpleNamespace:
    msg = SimpleNamespace(content=content, tool_calls=calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="tool_calls" if calls else "stop")])


class ScriptedLLM:
    """`script(messages)` → balasan berikutnya. Mencatat semua request."""

    def __init__(self, script):
        self.script = script
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.script(kwargs["messages"], len(self.requests))


def _tool_results(messages: list[dict]) -> list[dict]:
    return [json.loads(m["content"]) for m in messages if m["role"] == "tool"]


def happy_script(summary_for=None, recommendation="Uji kandidat #1 lebih dulu, keputusan tetap pada formulator.", n_request=3):
    def script(messages, turn):
        if turn == 1:
            return _reply(calls=[_call("designer_propose", {"n": n_request}, 1)])
        cands = next(r for r in _tool_results(messages) if "candidates" in r)["candidates"]
        ids = [c["candidate_id"] for c in cands]
        if turn == 2:
            return _reply(calls=[_call("guardian_check", {"candidate_id": cid}, 10 + i) for i, cid in enumerate(ids)])
        if turn == 3:
            calls = []
            for i, cid in enumerate(ids[:2]):
                calls.append(_call("scout_market", {"candidate_id": cid}, 20 + i))
                calls.append(_call("scout_literature", {"candidate_id": cid, "query": "niacinamide carbomer gel stability"}, 30 + i))
            return _reply(calls=calls)
        texts = []
        for c in cands:
            text = summary_for(c) if summary_for else (
                f"Prediksi viskositas {c['prediction']['VISCOSITY_CP']:,} cP dan pH {c['prediction']['PH']}. "
                f"Peluang memenuhi seluruh spesifikasi {round(c['prediction']['P_TARGET'] * 100)}%. Disarankan uji lab."
            ).replace(",", ".")
            texts.append({"candidate_id": c["candidate_id"], "text": text})
        return _reply(content="```json\n" + json.dumps({"summaries": texts, "recommendation": recommendation}) + "\n```")

    return script


@pytest.fixture()
def orch_api(api, monkeypatch):
    """API dengan LLM dianggap siap dan klien OpenAI diganti `ScriptedLLM` yang dipasang tiap test."""
    holder: dict[str, Any] = {}
    monkeypatch.setattr(api.state.llm, "ready", lambda force=False: True)
    monkeypatch.setattr(orch, "make_openai_client", lambda settings=None: holder["llm"])
    api.holder = holder
    return api


def _run(api, **body) -> dict:
    r = api.post("/api/v1/runs", json={"brief_id": BRIEF, "n": 3, "use_orchestrator": True, **body})
    assert r.status_code == 202, r.text
    return wait_run(api, r.json()["data"]["run_id"])


# Validator -------------------------------------------------------------------

def test_validator_numbers() -> None:
    allowed = collect_numbers({"VISCOSITY_CP": 6452.861, "PH": 5.62, "P_TARGET": 0.581, "COST": 28346.0, "rank": 1})
    assert validate_text("Viskositas 6.453 cP, pH 5,62, peluang 58%, biaya Rp28.346/kg, kandidat #1.", allowed).ok
    assert validate_text("Viskositas 6453 cP dan pH 5.6 dengan peluang 0,58.", allowed).ok
    bad = validate_text("Viskositas 7.000 cP dan pH 5,62.", allowed)
    assert not bad.ok and bad.reason == "number" and bad.offending == ["7.000"]
    assert validate_text("Rentang 95% dari model D50 dan CI95.", allowed).ok
    fake_cost = validate_text("Biaya Rp99.999/kg atau IDR 12.345.", allowed)
    assert not fake_cost.ok and fake_cost.offending == ["99.999", "12.345"]


def test_validator_claims() -> None:
    assert not check_claims("Formula ini aman dan halal.").ok
    assert not check_claims("Dijamin lolos BPOM.").ok
    assert check_claims("Perlu verifikasi halal dan sertifikat halal pemasok (asumsi tim).").ok
    assert check_claims("Pastikan keamanan diuji di lab.").ok
    assert not validate_text("", set()).ok
    assert not check_claims("Kandidat ini memenuhi semua spesifikasi target.").ok
    assert check_claims("Peluang memenuhi seluruh spesifikasi cukup tinggi.").ok


def test_orchestrator_forces_final_answer_at_step_limit(orch_api, monkeypatch) -> None:
    monkeypatch.setenv("ORCH_MAX_STEPS", "3")
    orch_api.state.settings = get_settings(refresh=True)
    seen: list[dict] = []

    def script(messages, turn):
        req = orch_api.holder["llm"].requests[-1]
        seen.append({"turn": turn, "tool_choice": req["tool_choice"]})
        if req["tool_choice"] == "none":
            return _reply(content=json.dumps({"summaries": [], "recommendation": "Uji kandidat #1 dulu."}))
        if turn == 1:
            return _reply(calls=[_call("designer_propose", {"n": 3}, 1)])
        cands = next(r for r in _tool_results(messages) if "candidates" in r)["candidates"]
        return _reply(calls=[_call("guardian_check", {"candidate_id": cands[0]["candidate_id"]}, turn)])

    orch_api.holder["llm"] = ScriptedLLM(script)
    run = _run(orch_api)
    assert [s["tool_choice"] for s in seen] == ["auto", "auto", "none"]
    assert run["llm_status"] == "ok"
    assert run["recommendation"] == "Uji kandidat #1 dulu."


CLAIM_CONTEXT_OK = [
    "Perlu verifikasi halal dan sertifikat halal pemasok (asumsi tim).",
    "Terdapat peringatan sumber gliserin yang perlu dicek status halal.",
    "Periksa sertifikat halal untuk semua bahan kritis sebelum lanjut.",
    "Guardian memberi catatan halal untuk glycerin dan emulsifier.",
    "Terdapat peringatan halal untuk sumber glycerin.",
    "Status halal dan BPOM perlu diverifikasi oleh tim regulasi.",
    "Formula ini tidak dapat dinyatakan halal tanpa sertifikat pemasok.",
    "Kadar phenoxyethanol di bawah batas BPOM (asumsi tim).",
    "Sumber bahan hewani perlu dicek terkait kriteria halal.",
    "Glycerin: halal pemasok perlu dicek.",
    "Tidak dijamin halal; minta dokumen pemasok.",
    "Belum pasti stabil, disarankan uji lab.",
]
CLAIM_REAL = [
    "Formula ini aman dan halal.",
    "Formula ini halal.",
    "Kandidat ini aman untuk kulit sensitif.",
    "Perlu uji lab, formula halal.",
    "Sudah halal dan siap produksi.",
    "Dijamin lolos BPOM.",
    "Lolos BPOM tanpa masalah.",
    "Kandidat #1 terbaik untuk diuji.",
    "Pasti stabil.",
    "Guardian tidak menemukan masalah dan formula aman.",
]


@pytest.mark.parametrize("text", CLAIM_CONTEXT_OK)
def test_claim_words_allowed_in_warning_context(text) -> None:
    assert check_claims(text).ok, check_claims(text).offending


@pytest.mark.parametrize("text", CLAIM_REAL)
def test_claim_words_rejected_as_claims(text) -> None:
    assert not check_claims(text).ok


def _lit_scout(fake_agents, monkeypatch, query_for):
    scout = fake_agents["fp.scout"]
    monkeypatch.setattr(scout, "query_for", query_for, raising=False)

    def search(q, k=3):
        hits = [{"id": f"common-{i}", "pmcid": f"PMCC{i}", "title": f"Artikel umum {i}", "score": 0.95 - 0.01 * i} for i in range(3)]
        hits += [{"id": f"{q}-{i}", "pmcid": f"PMC-{q}-{i}", "title": f"Artikel {q} {i}", "score": 0.8 - 0.01 * i} for i in range(5)]
        return [{"type": "literature", "year": 2022, "journal": "Jurnal uji", "url": "https://europepmc.org/", "snippet": "abstrak", **h} for h in hits[:k]]

    monkeypatch.setattr(scout, "search", search)


def _pmcids(cand):
    return {e["detail"]["pmcid"] for e in cand["evidence"] if e["type"] == "literature"}


def test_orchestrator_repeated_llm_query_is_diversified(orch_api, fake_agents, monkeypatch) -> None:
    _lit_scout(fake_agents, monkeypatch, lambda f: f"glycerin {f['GLYCERIN']} emulsion stability")
    orch_api.holder["llm"] = ScriptedLLM(happy_script())
    run = _run(orch_api)
    started = [e["detail"] for e in run["events"] if e["action"] == "literature" and e["status"] == "started"]
    assert [d["query_source"] for d in started] == ["llm", "query_for_dedup"]
    assert started[0]["query"] != started[1]["query"]
    first, second = run["candidates"][0], run["candidates"][1]
    assert len(_pmcids(first)) == 3 and len(_pmcids(second)) == 3
    assert _pmcids(first).isdisjoint(_pmcids(second))


def test_deterministic_literature_prefers_unseen_hits(api, fake_agents, monkeypatch) -> None:
    _lit_scout(fake_agents, monkeypatch, lambda f: "niacinamide emulsion stability")
    r = api.post("/api/v1/runs", json={"brief_id": BRIEF, "n": 3, "use_orchestrator": False})
    run = wait_run(api, r.json()["data"]["run_id"])
    first, second = run["candidates"][0], run["candidates"][1]
    assert _pmcids(first) == {"PMCC0", "PMCC1", "PMCC2"}
    assert len(_pmcids(second)) == 3 and _pmcids(first).isdisjoint(_pmcids(second))


def test_rejected_summary_event_has_text_preview(orch_api) -> None:
    orch_api.holder["llm"] = ScriptedLLM(happy_script(summary_for=lambda c: "Formula ini aman dan halal."))
    run = _run(orch_api)
    rejected = [e["detail"] for e in run["events"] if e["action"] == "summary_rejected_claim"]
    assert rejected and rejected[0]["text_preview"] == "Formula ini aman dan halal."


def test_template_uses_indonesian_numbers_and_passes_validator() -> None:
    from fp.orchestrator import templates

    pred = S.Prediction(
        VISCOSITY_CP=6935.2, VISCOSITY_CP_CI95=(5447.1, 8830.4), PH=5.61, PH_CI95=(5.3, 5.9), D50_UM=1.18, D50_UM_CI95=(0.9, 1.5),
        P_STABLE=0.996, COST_IDR_PER_KG=27091.4, P_SPECS={"P_VISC": 0.9, "P_PH": 1.0, "P_D50": 1.0, "P_STABLE": 0.996, "DET_OK": 1.0},
        P_TARGET=0.62, UNCERTAINTY=0.3, model_version="gp-global-v1",
    )
    gate = S.Gate(status="review", issues=[S.Issue(code="HALAL_SOURCE_CHECK", severity="warning", message="GLYCERIN: sumber perlu dicek (asumsi tim).")])
    text = templates.summary_text(pred, gate)
    assert text.startswith("Prediksi viskositas 6.935 cP (95%: 5.447–8.830), pH 5,6, droplet 1,2 µm, peluang stabil 100%.")
    assert "spesifikasi 62%; biaya bahan Rp27.091/kg" in text
    assert validate_text(text, collect_numbers(pred, gate)).ok


def test_tool_definitions_shape() -> None:
    names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
    assert names == ["designer_propose", "designer_explain", "guardian_check", "scout_literature", "scout_market"]
    for t in TOOL_DEFINITIONS:
        fn = t["function"]
        assert "agent" in fn["description"]
        assert fn["parameters"]["required"] == list(fn["parameters"]["properties"])


class _Box:
    def __init__(self):
        self.calls = []

    def designer_propose(self, n):
        self.calls.append(("propose", n))
        return {"candidates": []}

    def designer_explain(self, candidate_id):
        raise LookupError("unknown candidate_id")

    def guardian_check(self, candidate_id):
        return {"gate": "ok"}

    def scout_literature(self, candidate_id, query):
        self.calls.append(("lit", query))
        return {"evidence": []}

    def scout_market(self, candidate_id):
        return {"evidence": []}


def test_execute_tool_arguments() -> None:
    box, events = _Box(), []
    emit = lambda *a, **k: events.append(a)
    assert "error" in execute_tool(box, "guardian_check", "{not json", 3, emit)
    assert "error" in execute_tool(box, "guardian_check", json.dumps({"wrong": 1}), 3, emit)
    assert execute_tool(box, "designer_explain", json.dumps({"candidate_id": "cand_x"}), 3, emit) == {"error": "unknown candidate_id"}
    assert "error" in execute_tool(box, "tidak_ada", "{}", 3, emit)
    execute_tool(box, "designer_propose", json.dumps({"n": 9}), 3, emit)
    assert box.calls[-1] == ("propose", 3)
    assert events and events[-1][1] == "policy_override" and events[-1][3]["requested_n"] == 9
    execute_tool(box, "scout_literature", json.dumps({"candidate_id": "c", "query": "x" * 500}), 3, emit)
    assert len(box.calls[-1][1]) == 200


def test_parse_final_json_tolerates_fences_and_text() -> None:
    assert orch.parse_final_json('```json\n{"summaries": []}\n```') == {"summaries": []}
    assert orch.parse_final_json('Berikut hasilnya: {"summaries": [], "recommendation": "x"}')["recommendation"] == "x"
    with pytest.raises(ValueError):
        orch.parse_final_json("tidak ada json")


# Integrasi lewat API -------------------------------------------------------------

def test_orchestrated_run_ok(orch_api) -> None:
    llm = ScriptedLLM(happy_script())
    orch_api.holder["llm"] = llm
    run = S.Run.model_validate(_run(orch_api))
    assert run.status == "done", run.error
    assert run.llm_status == "ok"
    assert [c.summary.source for c in run.candidates] == ["llm", "llm", "llm"], [c.summary for c in run.candidates]
    assert run.recommendation == "Uji kandidat #1 lebih dulu, keputusan tetap pada formulator."
    assert not any(e.action == "policy_enforced" for e in run.events)
    steps = [e for e in run.events if e.action == "llm_step"]
    assert [e.detail["step"] for e in steps] == [1, 2, 3, 4]
    assert llm.requests[0]["tools"] == TOOL_DEFINITIONS
    assert llm.requests[0]["tool_choice"] == "auto"
    assert "Orchestrator FormulaPilot" in llm.requests[0]["messages"][0]["content"]
    assert {e.type for e in run.candidates[0].evidence} == {"market", "literature"}


def test_candidate_ids_in_llm_text_become_ranks(orch_api) -> None:
    def summary_for(c):
        return f"Uji lab kandidat {c['candidate_id']} untuk memastikan stabilitas."

    captured: dict[str, str] = {}

    def script(messages, turn):
        reply = happy_script(summary_for=summary_for)(messages, turn)
        if turn >= 4:
            cands = next(r for r in _tool_results(messages) if "candidates" in r)["candidates"]
            captured["first"] = cands[0]["candidate_id"]
            body = json.loads(reply.choices[0].message.content.strip("`\njson"))
            body["recommendation"] = f"Uji kandidat {cands[0]['candidate_id']} lebih dulu."
            reply.choices[0].message.content = json.dumps(body)
        return reply

    orch_api.holder["llm"] = ScriptedLLM(script)
    run = _run(orch_api)
    assert run["candidates"][0]["summary"]["text"] == "Uji lab kandidat #1 untuk memastikan stabilitas."
    assert run["recommendation"] == "Uji kandidat #1 lebih dulu."
    assert captured["first"] not in json.dumps(run["candidates"][0]["summary"])


def test_orchestrator_n_is_forced(orch_api) -> None:
    orch_api.holder["llm"] = ScriptedLLM(happy_script(n_request=5))
    run = _run(orch_api, n=2)
    assert len(run["candidates"]) == 2
    override = [e for e in run["events"] if e["action"] == "policy_override"]
    assert override and override[0]["detail"]["requested_n"] == 5 and override[0]["detail"]["used_n"] == 2


def test_orchestrator_rejects_foreign_numbers_and_claims(orch_api) -> None:
    def summary_for(c):
        if c["rank"] == 1:
            return "Viskositas 99.999 cP, peluang 77%."
        if c["rank"] == 2:
            return "Formula ini aman dan halal untuk kulit."
        return "Disarankan uji lab untuk kandidat ini."

    orch_api.holder["llm"] = ScriptedLLM(happy_script(summary_for=summary_for, recommendation="Kandidat #1 terbaik dan dijamin."))
    run = _run(orch_api)
    assert run["llm_status"] == "ok"
    sources = [c["summary"]["source"] for c in run["candidates"]]
    assert sources == ["template", "template", "llm"]
    reasons = [c["summary"]["reason"] for c in run["candidates"]]
    assert reasons[:2] == ["rejected_number", "rejected_claim"]
    actions = [e["action"] for e in run["events"]]
    assert "summary_rejected_number" in actions and "summary_rejected_claim" in actions
    assert run["recommendation"].startswith("Urutan uji yang disarankan")


def test_orchestrator_timeout_falls_back_to_template(orch_api) -> None:
    def script(messages, turn):
        raise TimeoutError("LLM tidak menjawab")

    orch_api.holder["llm"] = ScriptedLLM(script)
    run = _run(orch_api)
    assert run["status"] == "done"
    assert run["llm_status"] == "degraded"
    assert all(c["summary"]["source"] == "template" for c in run["candidates"])
    assert any(e["agent"] == "orchestrator" and e["action"] == "error" and e["status"] == "failed" for e in run["events"])


def test_orchestrator_invalid_final_json_is_degraded(orch_api) -> None:
    def script(messages, turn):
        if turn == 1:
            return _reply(calls=[_call("designer_propose", {"n": 3}, 1)])
        return _reply(content="Maaf, saya tidak bisa membuat JSON.")

    orch_api.holder["llm"] = ScriptedLLM(script)
    run = _run(orch_api)
    assert run["status"] == "done" and run["llm_status"] == "degraded"
    assert len(run["candidates"]) == 3


def test_policy_enforcement_runs_missed_guardian_and_scout(orch_api) -> None:
    def script(messages, turn):
        if turn == 1:
            return _reply(calls=[_call("designer_propose", {"n": 3}, 1)])
        cands = next(r for r in _tool_results(messages) if "candidates" in r)["candidates"]
        return _reply(content=json.dumps({"summaries": [{"candidate_id": cands[0]["candidate_id"], "text": "Disarankan uji lab."}]}))

    orch_api.holder["llm"] = ScriptedLLM(script)
    run = _run(orch_api)
    assert run["llm_status"] == "ok"
    enforced = [e["detail"]["step"] for e in run["events"] if e["action"] == "policy_enforced"]
    assert enforced.count("guardian_check") == 3
    assert enforced.count("scout_market") == 2 and enforced.count("scout_literature") == 2
    assert [c["gate"]["status"] for c in run["candidates"]] == ["review", "pass", "blocked"]
    assert [c["summary"]["source"] for c in run["candidates"]] == ["llm", "template", "template"]
    assert run["recommendation"].startswith("Urutan uji yang disarankan")


def test_orchestrator_unknown_candidate_id_goes_back_to_llm(orch_api) -> None:
    seen: list[dict] = []

    def script(messages, turn):
        if turn == 1:
            return _reply(calls=[_call("designer_propose", {"n": 3}, 1)])
        if turn == 2:
            return _reply(calls=[_call("guardian_check", {"candidate_id": "cand_palsu"}, 2)])
        seen.extend(_tool_results(messages))
        return _reply(content=json.dumps({"summaries": []}))

    orch_api.holder["llm"] = ScriptedLLM(script)
    run = _run(orch_api)
    assert {"error": "unknown candidate_id"} in seen
    assert run["status"] == "done"


@pytest.mark.skipif(os.environ.get("FP_LIVE_LLM") != "1", reason="set FP_LIVE_LLM=1 untuk uji dengan llama-server asli")
def test_live_llm_orchestration(runtime_dir, fake_agents, monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", os.environ.get("FP_LIVE_LLM_URL", "http://localhost:8080/v1"))
    app = create_app(get_settings(refresh=True))
    with TestClient(app) as c:
        app.state.fp.set_designer("global", "gp-global-v1", FakeDesigner())
        r = c.post("/api/v1/runs", json={"brief_id": BRIEF, "n": 3, "use_orchestrator": True})
        run = wait_run(c, r.json()["data"]["run_id"], timeout=120)
    print(json.dumps({
        "llm_status": run["llm_status"],
        "recommendation": run["recommendation"],
        "summaries": [(c["rank"], c["summary"]["source"], c["summary"]["reason"], c["summary"]["text"]) for c in run["candidates"]],
        "events": [(e["seq"], e["agent"], e["action"], e["status"], e.get("duration_ms"), {k: v for k, v in e["detail"].items() if k in ("step", "tool_calls", "offending", "reason", "error", "requested_n")}) for e in run["events"]],
    }, ensure_ascii=False, indent=1))
    assert run["status"] == "done"
