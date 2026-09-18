"""Fixture di contracts/fixtures harus selalu valid terhadap fp/schemas.py. Pemilik: David (B)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from fp import schemas as S
from fp.io_utils import atomic_path, dumps_json, read_json, write_json

FIXTURE_MODELS = {
    "run_done.json": S.Run,
    "candidate_pass.json": S.Candidate,
    "candidate_review.json": S.Candidate,
    "candidate_blocked.json": S.Candidate,
    "progress.json": S.Progress,
    "lab_test.json": S.LabTestResponse,
    "health.json": S.Health,
    "palette.json": S.Palette,
    "replay_session.json": S.ReplaySession,
    "evaluation_min.json": S.EvaluationReport,
    "error_gate_blocked.json": S.ErrorEnvelope,
}


def _load(fixtures_dir: Path, name: str):
    return json.loads((fixtures_dir / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,model", sorted(FIXTURE_MODELS.items()))
def test_fixture_valid(fixtures_dir: Path, name: str, model) -> None:
    model.model_validate(_load(fixtures_dir, name))


def test_briefs_fixture(fixtures_dir: Path) -> None:
    briefs = TypeAdapter(list[S.Brief]).validate_python(_load(fixtures_dir, "briefs.json"))
    assert briefs[0].brief_id == "niacinamide_gel_cream"


def test_every_fixture_is_checked(fixtures_dir: Path) -> None:
    on_disk = {p.name for p in fixtures_dir.glob("*.json")}
    assert on_disk == set(FIXTURE_MODELS) | {"briefs.json"}


def test_fixture_formulas_total_100(fixtures_dir: Path) -> None:
    run = S.Run.model_validate(_load(fixtures_dir, "run_done.json"))
    assert [c.gate.status for c in run.candidates] == ["review", "pass", "blocked"]
    for c in run.candidates:
        total = sum(getattr(c.formula, k) for k in S.INGREDIENT_FIELDS) + c.formula.AQUA
        assert abs(total - 100) < 1e-3


def test_event_seq_strictly_increasing(fixtures_dir: Path) -> None:
    run = S.Run.model_validate(_load(fixtures_dir, "run_done.json"))
    seqs = [e.seq for e in run.events]
    assert seqs == list(range(1, len(seqs) + 1))


def test_specs_rejects_bad_range() -> None:
    with pytest.raises(ValueError):
        S.Specs(NIACINAMIDE_MIN_PCT=4, VISCOSITY_CP=(12000, 4000), PH=(5, 6.5), D50_UM_MAX=3, COST_IDR_PER_KG_MAX=50000)


def test_run_create_rules() -> None:
    assert S.RunCreate(brief_id="niacinamide_gel_cream").n == 3
    with pytest.raises(ValueError):
        S.RunCreate(brief_id="x", n=6)
    with pytest.raises(ValueError):
        S.RunCreate(brief_id="x", run_mode="replay")


def test_formula_field_order() -> None:
    assert S.FORMULA_FIELDS[:10] == S.INGREDIENT_FIELDS
    assert S.FORMULA_FIELDS[10:] == ("AQUA", "RPM", "HMIN", "TEMP")
    assert len(S.SPECS_MET_KEYS) == 7


def test_atomic_json_roundtrip(runtime_dir: Path) -> None:
    target = runtime_dir / "sub" / "x.json"
    write_json(target, {"a": math.nan, "b": (1, 2), "c": S.Issue(code="X", severity="info", message="m")})
    assert read_json(target) == {"a": None, "b": [1, 2], "c": {"code": "X", "severity": "info", "message": "m", "field": None}}
    assert not [p for p in target.parent.iterdir() if p.name.startswith(".")]


def test_atomic_failure_keeps_old_file(runtime_dir: Path) -> None:
    target = runtime_dir / "keep.csv.gz"
    write_json(target, {"v": 1})
    with pytest.raises(RuntimeError):
        with atomic_path(target) as tmp:
            assert tmp.name.endswith(".csv.gz")
            tmp.write_text("half")
            raise RuntimeError("gagal di tengah")
    assert read_json(target) == {"v": 1}
    assert [p.name for p in runtime_dir.iterdir() if p.name.startswith(".")] == []


def test_read_json_default(runtime_dir: Path) -> None:
    assert read_json(runtime_dir / "missing.json", default=None) is None
    assert dumps_json({"x": 1}, indent=None) == '{"x": 1}'


def test_config_uses_runtime_dir(runtime_dir: Path) -> None:
    from fp.config import get_settings, now_iso

    s = get_settings()
    assert s.runtime_dir == runtime_dir
    assert s.db_path == runtime_dir / "app.db"
    assert s.llm_base_url.startswith("http://127.0.0.1:9")
    assert now_iso().endswith("+07:00")
