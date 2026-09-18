"""Membuat dan menjalankan run di thread (PRD §14.6 `POST /runs`). Pemilik: David (B)."""

from __future__ import annotations

import logging
import secrets
import threading
import time
from datetime import datetime
from typing import Any, Optional

from fp import schemas as S
from fp.config import WIB, now_iso, now_wib
from fp.orchestrator import loop

from .. import repo
from ..errors import ApiError, conflict, not_found, unavailable
from ..state import AppState
from . import replay
from .pipeline import Pipeline

log = logging.getLogger("formulapilot.runs")

_start_lock = threading.Lock()


def _brief(state: AppState, brief_id: str) -> S.Brief:
    briefs = state.briefs.get()
    if briefs is None:
        raise unavailable("DATA_NOT_READY", f"Data brief belum tersedia ({state.briefs.error}).")
    brief = briefs.get(brief_id)
    if brief is None:
        raise not_found("BRIEF_NOT_FOUND", f"Brief '{brief_id}' tidak ditemukan.")
    return brief


def _tested_formulas(state: AppState, scope: str) -> list[S.Formula]:
    out = []
    for row in repo.active_lab_rows(state.db, scope):
        try:
            out.append(S.Formula.model_validate_json(row["formula_json"]))
        except ValueError:
            continue
    return out


def create_run(state: AppState, req: S.RunCreate) -> S.RunCreated:
    brief = _brief(state, req.brief_id)
    specs = req.specs or brief.specs

    scope = repo.scope_for(req.run_mode, req.session_id)
    pool = None
    if req.run_mode == "replay":
        session = repo.get_replay_session(state.db, req.session_id) if req.session_id else None
        if session is None:
            raise not_found("SESSION_NOT_FOUND", f"Sesi replay '{req.session_id}' tidak ditemukan.")
        if session["brief_id"] != brief.brief_id:
            raise ApiError(422, "VALIDATION_ERROR", f"brief_id harus sama dengan brief sesi ({session['brief_id']}).")
        entry = replay.session_designer(state, req.session_id)
        pool = replay.pool_frame(state, session)
    else:
        entry = state.get_designer(scope)
    if entry is None:
        reason = state.model_error or "model belum dimuat"
        raise unavailable("MODEL_NOT_READY", f"Model Designer belum siap: {reason}.")
    model_version, designer = entry

    with _start_lock:
        running = repo.running_run_for_scope(state.db, scope)
        if running and expire_if_stuck(state, repo.get_run_row(state.db, running)):
            running = None
        if running:
            raise conflict("RUN_IN_PROGRESS", f"Run {running} masih berjalan. Tunggu sampai selesai.")
        run = S.Run(
            run_id=repo.new_id("run"),
            run_mode=req.run_mode,
            session_id=req.session_id,
            brief_id=brief.brief_id,
            specs=specs,
            n=req.n,
            use_orchestrator=req.use_orchestrator,
            status="running",
            llm_status="not_used",
            model_version=model_version,
            created_at=now_wib(),
        )
        repo.insert_run(state.db, run)

    seed = secrets.randbelow(2**31 - 1)
    repo.add_event(
        state.db,
        run.run_id,
        "system",
        "run_started",
        "done",
        {"run_mode": run.run_mode, "brief_id": run.brief_id, "n": run.n, "use_orchestrator": run.use_orchestrator, "seed": seed},
    )
    exclude = _tested_formulas(state, scope) if pool is None else []
    state.executor.submit(_execute, state, run, brief, designer, seed, exclude, pool)
    return S.RunCreated(run_id=run.run_id, status="running")


def _execute(
    state: AppState, run: S.Run, brief: S.Brief, designer: Any, seed: int, exclude: list[S.Formula], pool: Any = None
) -> None:
    started = time.perf_counter()
    pipeline = Pipeline(state, run, designer, seed, exclude, pool)
    llm_status = "not_used"
    recommendation: Optional[str] = None
    try:
        summaries: dict[str, str] = {}
        if run.use_orchestrator:
            if state.llm.ready(force=True):
                result = loop.run_orchestrated(
                    pipeline,
                    brief.name,
                    run.specs.model_dump(mode="json"),
                    run.n,
                    state.settings,
                    emit=pipeline.emit,
                )
                llm_status = result.llm_status
                summaries = result.summaries if result.llm_status == "ok" else {}
                recommendation = result.recommendation if result.llm_status == "ok" else None
            else:
                llm_status = "degraded"
                pipeline.emit("orchestrator", "error", "failed", {"reason": "llm_not_ready", "error": state.llm.last_error})
        pipeline.enforce_policy(summaries)
        recommendation = pipeline.validated_recommendation(recommendation)
        duration = int((time.perf_counter() - started) * 1000)
        pipeline.emit("system", "run_finished", "done", {"status": "done", "duration_ms": duration}, duration)
        repo.update_run(
            state.db,
            run.run_id,
            only_if_running=True,
            status="done",
            llm_status=llm_status,
            recommendation=recommendation or pipeline.recommendation(),
            finished_at=now_iso(),
        )
    except Exception as exc:
        log.exception("run %s gagal", run.run_id)
        message = f"{type(exc).__name__}: {exc}"[:500]
        duration = int((time.perf_counter() - started) * 1000)
        try:
            pipeline.emit("system", "error", "failed", {"error": message}, duration)
        finally:
            repo.update_run(
                state.db, run.run_id, only_if_running=True, status="failed", llm_status=llm_status, error=message, finished_at=now_iso()
            )


def expire_if_stuck(state: AppState, row: Any) -> bool:
    """Run yang masih `running` melewati batas waktu ditandai `failed` agar UI tidak polling selamanya."""
    if row is None or row["status"] != "running":
        return False
    age = (datetime.now(WIB) - datetime.fromisoformat(row["created_at"])).total_seconds()
    if age <= state.settings.run_timeout_s:
        return False
    message = f"Run melebihi batas waktu {state.settings.run_timeout_s:.0f} detik dan dihentikan."
    if not repo.update_run(state.db, row["run_id"], only_if_running=True, status="failed", error=message, finished_at=now_iso()):
        return False
    repo.add_event(state.db, row["run_id"], "system", "error", "failed", {"error": message, "reason": "run_timeout"})
    log.warning("run %s ditandai failed: timeout %.0fs", row["run_id"], age)
    return True


def get_run(state: AppState, run_id: str, after_seq: int = 0) -> S.Run:
    expire_if_stuck(state, repo.get_run_row(state.db, run_id))
    run = repo.build_run(state.db, run_id, after_seq)
    if run is None:
        raise not_found("RUN_NOT_FOUND", f"Run '{run_id}' tidak ditemukan.")
    return run
