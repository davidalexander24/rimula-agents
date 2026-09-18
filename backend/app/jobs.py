"""Job agent "Run now" dan status agent (PRD §3.3 US-12, §14.5 `/agents/*`). Pemilik: David (B).

- designer → `designer_retrain`: retrain model global dari historical + hasil lab aktif.
- scout → `scout_reindex`: muat ulang indeks Scout dan data market dari artefak terbaru (build berat tetap lewat
  `scripts/build_scout.sh` + heavy.sh, R18).
- guardian → `guardian_recheck`: periksa ulang kandidat yang belum diputuskan pada run explore terakhir.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from fp import schemas as S

from . import repo
from .errors import conflict, not_found, unavailable
from .state import AppState, optional_module

log = logging.getLogger("formulapilot.jobs")

AGENT_JOBS = {"designer": "designer_retrain", "scout": "scout_reindex", "guardian": "guardian_recheck"}

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fp-job")
_start_lock = threading.Lock()


def _retrain(state: AppState) -> dict[str, Any]:
    from .services import training

    if state.get_designer("global") is None:
        raise RuntimeError(f"model global belum siap: {state.model_error}")
    version, _, n_train = training.retrain(state, "global")
    return {"model_version": version, "n_train": n_train}


def _reindex(state: AppState) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    for name in ("fp.scout", "fp.market"):
        module, err = optional_module(name)
        key = name.split(".")[1]
        if module is None:
            detail[key] = {"ready": False, "reason": err}
            continue
        warm = getattr(module, "warmup", None)
        if callable(warm):
            warm()
        detail[key] = state.optional_status(name)
    return detail


def _recheck(state: AppState) -> dict[str, Any]:
    from .services.pipeline import Pipeline

    with state.db.read() as conn:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE status = 'done' AND run_mode = 'explore' ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return {"run_id": None, "n_checked": 0, "changed": []}
    run = repo.build_run(state.db, row["run_id"], after_seq=10**9)
    entry = state.get_designer("global")
    pipeline = Pipeline(state, run, entry[1] if entry else None, seed=0)
    changed = []
    checked = 0
    for cand in run.candidates:
        if cand.decision is not None:
            continue
        pipeline.candidates[cand.candidate_id] = cand
        before = cand.gate.status
        pipeline.guardian_check(cand.candidate_id)
        after = pipeline.candidates[cand.candidate_id].gate.status
        checked += 1
        if after != before:
            changed.append({"candidate_id": cand.candidate_id, "from": before, "to": after})
    return {"run_id": run.run_id, "n_checked": checked, "changed": changed}


RUNNERS: dict[str, Callable[[AppState], dict[str, Any]]] = {
    "designer_retrain": _retrain,
    "scout_reindex": _reindex,
    "guardian_recheck": _recheck,
}


def _execute(state: AppState, job_id: str, kind: str) -> None:
    repo.update_job(state.db, job_id, "running", started=True)
    try:
        detail = RUNNERS[kind](state)
    except Exception as exc:
        log.exception("job %s (%s) gagal", job_id, kind)
        repo.update_job(state.db, job_id, "failed", {"error": f"{type(exc).__name__}: {exc}"[:500]}, finished=True)
    else:
        repo.update_job(state.db, job_id, "done", detail, finished=True)


def start_job(state: AppState, agent: str, trigger: str = "manual") -> S.JobCreated:
    kind = AGENT_JOBS.get(agent)
    if kind is None:
        raise not_found("AGENT_NOT_FOUND", f"Agent '{agent}' tidak dikenal. Pilihan: {', '.join(AGENT_JOBS)}.")
    if kind == "designer_retrain" and state.get_designer("global") is None:
        raise unavailable("MODEL_NOT_READY", f"Model Designer belum siap: {state.model_error or 'model belum dimuat'}.")
    with _start_lock:
        active = repo.active_job(state.db, kind)
        if active is not None:
            raise conflict("JOB_RUNNING", f"Job {kind} masih berjalan ({active.job_id}).")
        job = S.Job(job_id=repo.new_id("job"), kind=kind, trigger=trigger, status="queued", detail={}, started_at=None)
        repo.insert_job(state.db, job)
    _executor.submit(_execute, state, job.job_id, kind)
    return S.JobCreated(job_id=job.job_id)


def agents_status(state: AppState) -> S.AgentsStatus:
    guardian_mod, _ = optional_module("fp.guardian")
    scheduler: Optional[Any] = getattr(state, "scheduler", None)
    active = scheduler is not None and bool(getattr(scheduler, "running", False))

    def nxt(job_id: Optional[str] = None):
        return scheduler.next_run(job_id) if active else None

    return S.AgentsStatus(
        designer=S.AgentStatus(ready=state.model_ready, last_job=repo.last_job(state.db, "designer_retrain"), next_run=nxt("designer")),
        guardian=S.AgentStatus(ready=guardian_mod is not None, last_job=repo.last_job(state.db, "guardian_recheck"), next_run=nxt("guardian")),
        scout=S.AgentStatus(ready=bool(state.optional_status("fp.scout").get("ready")), last_job=repo.last_job(state.db, "scout_reindex"), next_run=nxt("scout")),
        market=S.AgentStatus(ready=bool(state.optional_status("fp.market").get("ready"))),
        scheduler=S.AgentStatus(ready=active, next_run=nxt()),
    )


def market_summary(state: AppState) -> dict[str, Any]:
    module, err = optional_module("fp.market")
    if module is None or not state.optional_status("fp.market").get("ready"):
        raise not_found("MARKET_NOT_READY", f"Data pasar belum siap ({err or 'artefak market belum dibangun'}).")
    summary = module.summary() if hasattr(module, "summary") else module.stats()
    if not summary:
        raise not_found("MARKET_NOT_READY", "Data pasar belum siap (ringkasan kosong).")
    summary = dict(summary)
    summary.pop("examples", None)
    return summary
