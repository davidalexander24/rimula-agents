"""Mode replay: sesi di atas data historis yang disembunyikan (PRD §3.2, §10.4, §14.5, AC-07). Pemilik: David (B).

Pool yang diberikan ke Designer hanya berisi `record_id` + kolom formula. Hasil lab baris pool baru dibaca
saat kandidat diungkap (`reveal`), sehingga tidak ada nilai yang bocor sebelum waktunya.
"""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path
from typing import Any, Optional

from fp import schemas as S
from fp.config import now_wib

from .. import repo
from ..errors import ApiError, conflict, not_found, unavailable
from ..state import AppState, optional_module
from . import training
from .candidates import get_candidate

K_INITIAL = 10
HISTORICAL_VARIANT = "v1"

_hist_lock = threading.Lock()
_hist_cache: dict[str, tuple[float, Any]] = {}


def historical(state: AppState):
    import pandas as pd

    path = Path(state.historical_path)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        raise unavailable("DATA_NOT_READY", f"{path.name} belum ada (menunggu A-04).")
    with _hist_lock:
        cached = _hist_cache.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
        df = pd.read_csv(path)
        needed = ["record_id", *S.FORMULA_FIELDS, *S.LAB_OUTPUT_KEYS]
        missing = [c for c in needed if c not in df.columns]
        if missing:
            raise unavailable("DATA_NOT_READY", f"kolom {missing} tidak ada di {path.name}.")
        df = df.set_index("record_id", drop=False)
        _hist_cache[str(path)] = (mtime, df)
        return df


def _outputs(row: Any) -> dict[str, float]:
    return {k: float(row[k]) for k in S.LAB_OUTPUT_KEYS}


def _formula(row: Any) -> S.Formula:
    return S.Formula(**{k: float(row[k]) for k in S.FORMULA_FIELDS})


def _specs_met(formula: S.Formula, outputs: dict[str, float], specs: S.Specs) -> dict[str, bool]:
    palette, err = optional_module("fp.palette")
    if palette is None:
        raise unavailable("DATA_NOT_READY", f"fp.palette belum tersedia ({err}).")
    met = palette.meets_specs(formula.model_dump(), outputs, specs.model_dump(mode="json"))
    return {k: bool(met[k]) for k in S.SPECS_MET_KEYS}


def select_initial(hist, specs: S.Specs, k: int, seed: int) -> list[str]:
    """Pakai `fp.strategies.select_initial` (A-12) bila ada; jika belum, k baris acak ber-seed yang tidak memenuhi semua spesifikasi."""
    strategies, _ = optional_module("fp.strategies")
    helper = getattr(strategies, "select_initial", None) if strategies else None
    if callable(helper):
        chosen = helper(hist.reset_index(drop=True), specs.model_dump(mode="json"), k, seed)
        if hasattr(chosen, "columns") and "record_id" in chosen.columns:
            return [str(r) for r in chosen["record_id"]]
        return [str(r["record_id"]) if isinstance(r, dict) else str(r) for r in chosen]
    import numpy as np

    misses = [rid for rid, row in hist.iterrows() if not _specs_met(_formula(row), _outputs(row), specs)["ALL"]]
    if len(misses) < k:
        raise ApiError(422, "VALIDATION_ERROR", f"Hanya {len(misses)} baris historis yang belum memenuhi spesifikasi; butuh {k}.")
    rng = np.random.RandomState(seed % (2**32))
    return [str(misses[i]) for i in rng.choice(len(misses), size=k, replace=False)]


def training_table(hist, record_ids: list[str]):
    rows = hist.loc[record_ids]
    return rows[[*S.FORMULA_FIELDS, *training.TARGET_COLUMNS]].reset_index(drop=True)


def _session(state: AppState, session_id: str) -> dict:
    session = repo.get_replay_session(state.db, session_id)
    if session is None:
        raise not_found("SESSION_NOT_FOUND", f"Sesi replay '{session_id}' tidak ditemukan.")
    return session


def _brief_specs(state: AppState, brief_id: str) -> S.Specs:
    briefs = state.briefs.get() or {}
    brief = briefs.get(brief_id)
    if brief is None:
        raise not_found("BRIEF_NOT_FOUND", f"Brief '{brief_id}' tidak ditemukan.")
    return brief.specs


def session_designer(state: AppState, session_id: str) -> Optional[tuple[str, Any]]:
    scope = f"session:{session_id}"
    entry = state.get_designer(scope)
    if entry is not None:
        return entry
    row = repo.active_model_version(state.db, scope)
    if row is None or not Path(row["path"]).is_file():
        return None
    designer = state.load_designer_file(Path(row["path"]))
    state.set_designer(scope, row["version"], designer)
    return row["version"], designer


def pool_frame(state: AppState, session: dict):
    hist = historical(state)
    known = set(session["initial_record_ids"]) | set(session["revealed_record_ids"])
    pool = hist[~hist["record_id"].astype(str).isin(known)]
    return pool[["record_id", *S.FORMULA_FIELDS]].reset_index(drop=True)


def view(state: AppState, session_id: str, include_seed: bool, include_progress: bool) -> S.ReplaySession:
    session = _session(state, session_id)
    specs = _brief_specs(state, session["brief_id"])
    hist = historical(state)
    known = []
    for rid in [*session["initial_record_ids"], *session["revealed_record_ids"]]:
        row = hist.loc[rid]
        formula, outputs = _formula(row), _outputs(row)
        known.append(S.KnownRecord(record_id=rid, formula=formula, outputs=outputs, specs_met=_specs_met(formula, outputs, specs)))
    entry = session_designer(state, session_id)
    return S.ReplaySession(
        session_id=session_id,
        brief_id=session["brief_id"],
        seed=session["seed"] if include_seed else None,
        progress=repo.progress(state.db, f"session:{session_id}") if include_progress else None,
        known=known,
        pool_size=len(hist) - len(known),
        model_version=entry[0] if entry else "",
    )


def create_session(state: AppState, req: S.ReplaySessionCreate) -> S.ReplaySession:
    specs = _brief_specs(state, req.brief_id)
    template = state.get_designer("global")
    if template is None:
        raise unavailable("MODEL_NOT_READY", f"Model Designer belum siap: {state.model_error or 'model belum dimuat'}.")
    seed = req.seed if req.seed is not None else secrets.randbelow(2**31 - 1)
    hist = historical(state)
    initial = select_initial(hist, specs, K_INITIAL, seed)
    session_id = repo.new_id("rs")
    repo.insert_replay_session(state.db, session_id, req.brief_id, seed, initial)
    training.fit_new(state, f"session:{session_id}", training_table(hist, initial), template[1])
    return view(state, session_id, include_seed=True, include_progress=False)


def reveal(state: AppState, candidate_id: str) -> S.LabTestResponse:
    cand = get_candidate(state, candidate_id)
    if cand.origin != "pool":
        raise conflict("NOT_POOL", "Kandidat hasil eksplorasi diuji di Virtual Lab, bukan diungkap dari data historis.")
    if cand.decision != "approved":
        raise conflict("NOT_APPROVED", "Setujui kandidat terlebih dahulu sebelum hasil historisnya diungkap.")
    if cand.lab_result is not None:
        raise conflict("ALREADY_REVEALED", f"Hasil kandidat #{cand.rank} sudah diungkap.")
    run = repo.get_run_row(state.db, cand.run_id)
    session_id = run["session_id"]
    scope = f"session:{session_id}"
    specs = S.Specs.model_validate_json(run["specs_json"])
    hist = historical(state)

    with state.model_lock(f"lab:{scope}"):
        session = _session(state, session_id)
        rid = cand.source_record_id
        if rid in session["revealed_record_ids"] or repo.get_candidate(state.db, candidate_id).lab_result is not None:
            raise conflict("ALREADY_REVEALED", f"Baris {rid} sudah diungkap di sesi ini.")
        started = time.perf_counter()
        outputs = _outputs(hist.loc[rid])
        lab = S.LabResult(
            lab_result_id=repo.new_id("lab"),
            batch_index=repo.next_batch_index(state.db, scope),
            outputs=outputs,
            specs_met=_specs_met(cand.formula, outputs, specs),
            source="historical",
            variant=HISTORICAL_VARIANT,
            recorded_at=now_wib(),
        )
        repo.insert_lab_result(state.db, candidate_id, scope, lab)
        revealed = [*session["revealed_record_ids"], rid]
        hit = session["hit_at_batch"] or (lab.batch_index if lab.specs_met["ALL"] else None)
        repo.update_replay_session(state.db, session_id, revealed, hit)
        repo.add_event(
            state.db, cand.run_id, "lab", "lab_batch", "done",
            {"candidate_id": candidate_id, "record_id": rid, "batch_index": lab.batch_index, "all_specs_met": lab.specs_met["ALL"], "source": "historical"},
            int((time.perf_counter() - started) * 1000),
        )

    started = time.perf_counter()
    call = f"retrain#{lab.lab_result_id}"
    repo.add_event(state.db, cand.run_id, "designer", "retrain", "started", {"call": call, "scope": scope})
    try:
        session_designer(state, session_id)
        table = training_table(hist, [*session["initial_record_ids"], *revealed])
        version, _, n_train = training.retrain(state, scope, table)
    except Exception as exc:
        repo.add_event(
            state.db, cand.run_id, "designer", "retrain", "failed",
            {"call": call, "scope": scope, "error": f"{type(exc).__name__}: {exc}"[:300]},
            int((time.perf_counter() - started) * 1000),
        )
    else:
        repo.set_retrained_version(state.db, lab.lab_result_id, version)
        lab = lab.model_copy(update={"retrained_model_version": version})
        repo.add_event(
            state.db, cand.run_id, "designer", "retrain", "done",
            {"call": call, "scope": scope, "model_version": version, "n_train": n_train},
            int((time.perf_counter() - started) * 1000),
        )
    return S.LabTestResponse(candidate=get_candidate(state, candidate_id), lab_result=lab, progress=repo.progress(state.db, scope))
