"""Uji kandidat di Virtual Lab lalu retrain (PRD §8.1.4 aturan isolasi, §14.6). Pemilik: David (B).

Satu-satunya jalur backend ke "hasil lab" adalah `VirtualLab.run_batch` di file ini.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from fp import schemas as S
from fp.config import now_wib

from .. import repo
from ..errors import ApiError, conflict
from ..state import AppState, optional_module
from . import training
from .candidates import get_candidate


def lab_seed(candidate_id: str) -> int:
    return int(hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:8], 16)


def _outputs(raw: dict[str, Any]) -> dict[str, float]:
    out = {}
    for key in S.LAB_OUTPUT_KEYS:
        value = raw[key]
        out[key] = float(bool(value)) if key == "STABLE" else float(value)
    return out


def run_virtual_lab(state: AppState, formula: S.Formula, candidate_id: str) -> dict[str, float]:
    module, err = optional_module("fp.virtual_lab")
    if module is None:
        raise ApiError(503, "LAB_NOT_READY", f"Virtual Lab belum tersedia ({err}).")
    lab = module.VirtualLab(variant=state.settings.virtual_lab_variant, seed=lab_seed(candidate_id))
    return _outputs(lab.run_batch(formula.model_dump(), seed_override=lab_seed(candidate_id)))


def specs_met(formula: S.Formula, outputs: dict[str, float], specs: S.Specs) -> dict[str, bool]:
    palette, err = optional_module("fp.palette")
    if palette is None:
        raise ApiError(503, "LAB_NOT_READY", f"fp.palette belum tersedia ({err}).")
    met = palette.meets_specs(formula.model_dump(), outputs, specs.model_dump(mode="json"))
    return {k: bool(met[k]) for k in S.SPECS_MET_KEYS}


def run_candidate_test(state: AppState, candidate_id: str) -> S.LabTestResponse:
    cand = get_candidate(state, candidate_id)
    if cand.origin != "explore":
        raise conflict("NOT_EXPLORE", "Kandidat dari data historis diungkap lewat tombol replay, bukan diuji di Virtual Lab.")
    if cand.decision != "approved":
        raise conflict("NOT_APPROVED", "Setujui kandidat terlebih dahulu sebelum diuji.")
    if cand.lab_result is not None:
        raise conflict("ALREADY_TESTED", f"Kandidat #{cand.rank} sudah diuji (batch ke-{cand.lab_result.batch_index}).")

    run = repo.get_run_row(state.db, cand.run_id)
    specs = S.Specs.model_validate_json(run["specs_json"])

    with state.model_lock("lab:global"):
        if repo.get_candidate(state.db, candidate_id).lab_result is not None:
            raise conflict("ALREADY_TESTED", f"Kandidat #{cand.rank} sudah diuji.")
        started = time.perf_counter()
        outputs = run_virtual_lab(state, cand.formula, candidate_id)
        lab = S.LabResult(
            lab_result_id=repo.new_id("lab"),
            batch_index=repo.next_batch_index(state.db, "global"),
            outputs=outputs,
            specs_met=specs_met(cand.formula, outputs, specs),
            source="virtual_lab",
            variant=state.settings.virtual_lab_variant,
            recorded_at=now_wib(),
        )
        repo.insert_lab_result(state.db, candidate_id, "global", lab)
        repo.add_event(
            state.db, cand.run_id, "lab", "lab_batch", "done",
            {"candidate_id": candidate_id, "batch_index": lab.batch_index, "all_specs_met": lab.specs_met["ALL"], "variant": lab.variant},
            int((time.perf_counter() - started) * 1000),
        )

    started = time.perf_counter()
    repo.add_event(state.db, cand.run_id, "designer", "retrain", "started", {"call": f"retrain#{lab.lab_result_id}", "scope": "global"})
    try:
        version, _, n_train = training.retrain(state, "global")
    except Exception as exc:
        repo.add_event(
            state.db, cand.run_id, "designer", "retrain", "failed",
            {"call": f"retrain#{lab.lab_result_id}", "scope": "global", "error": f"{type(exc).__name__}: {exc}"[:300]},
            int((time.perf_counter() - started) * 1000),
        )
    else:
        repo.set_retrained_version(state.db, lab.lab_result_id, version)
        lab = lab.model_copy(update={"retrained_model_version": version})
        repo.add_event(
            state.db, cand.run_id, "designer", "retrain", "done",
            {"call": f"retrain#{lab.lab_result_id}", "scope": "global", "model_version": version, "n_train": n_train},
            int((time.perf_counter() - started) * 1000),
        )

    return S.LabTestResponse(
        candidate=get_candidate(state, candidate_id),
        lab_result=lab,
        progress=repo.progress(state.db, "global"),
    )
