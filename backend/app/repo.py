"""Akses tabel SQLite dan konversi baris ke `fp.schemas`. Pemilik: David (B)."""

from __future__ import annotations

import json
import secrets
import sqlite3
from typing import Any, Iterable, Optional

from fp import schemas as S
from fp.config import now_iso
from fp.io_utils import dumps_json

from .db import Database

TOTAL_SPECS = len(S.SPEC_KEYS)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _dump(obj: Any) -> str:
    return dumps_json(obj, indent=None)


def _load(text: Optional[str], default: Any = None) -> Any:
    if text is None or text == "":
        return default
    return json.loads(text)


def scope_for(run_mode: str, session_id: Optional[str]) -> str:
    return f"session:{session_id}" if run_mode == "replay" else "global"


# model_versions

def add_model_version(
    db: Database,
    version: str,
    scope: str,
    path: str,
    n_train: int,
    parent_version: Optional[str] = None,
    activate: bool = True,
    created_at: Optional[str] = None,
) -> None:
    with db.write() as conn:
        if activate:
            conn.execute("UPDATE model_versions SET is_active = 0 WHERE scope = ?", (scope,))
        conn.execute(
            "INSERT OR REPLACE INTO model_versions (version, scope, path, n_train, parent_version, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (version, scope, path, int(n_train), parent_version, 1 if activate else 0, created_at or now_iso()),
        )


def activate_model_version(db: Database, version: str) -> bool:
    with db.write() as conn:
        row = conn.execute("SELECT scope FROM model_versions WHERE version = ?", (version,)).fetchone()
        if row is None:
            return False
        conn.execute("UPDATE model_versions SET is_active = 0 WHERE scope = ?", (row["scope"],))
        conn.execute("UPDATE model_versions SET is_active = 1 WHERE version = ?", (version,))
        return True


def deactivate_scope(db: Database, scope: str) -> None:
    with db.write() as conn:
        conn.execute("UPDATE model_versions SET is_active = 0 WHERE scope = ?", (scope,))


def active_model_version(db: Database, scope: str) -> Optional[sqlite3.Row]:
    with db.read() as conn:
        return conn.execute(
            "SELECT * FROM model_versions WHERE scope = ? AND is_active = 1 ORDER BY created_at DESC LIMIT 1", (scope,)
        ).fetchone()


def get_model_version(db: Database, version: str) -> Optional[sqlite3.Row]:
    with db.read() as conn:
        return conn.execute("SELECT * FROM model_versions WHERE version = ?", (version,)).fetchone()


def list_model_versions(db: Database, scope: Optional[str] = None) -> list[S.ModelVersion]:
    sql = "SELECT * FROM model_versions"
    args: tuple = ()
    if scope:
        sql += " WHERE scope = ?"
        args = (scope,)
    sql += " ORDER BY created_at DESC, rowid DESC"
    with db.read() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [
        S.ModelVersion(
            version=r["version"],
            scope=r["scope"],
            n_train=r["n_train"],
            parent_version=r["parent_version"],
            is_active=bool(r["is_active"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def count_model_versions(db: Database, scope: str) -> int:
    with db.read() as conn:
        return conn.execute("SELECT COUNT(*) FROM model_versions WHERE scope = ?", (scope,)).fetchone()[0]


# runs

def insert_run(db: Database, run: S.Run) -> None:
    with db.write() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, run_mode, session_id, brief_id, specs_json, n, use_orchestrator, status, "
            "llm_status, model_version, recommendation, error, created_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.run_id,
                run.run_mode,
                run.session_id,
                run.brief_id,
                _dump(run.specs),
                run.n,
                int(run.use_orchestrator),
                run.status,
                run.llm_status,
                run.model_version,
                run.recommendation,
                run.error,
                run.created_at.isoformat(),
                run.finished_at.isoformat() if run.finished_at else None,
            ),
        )


_RUN_COLUMNS = {"status", "llm_status", "model_version", "recommendation", "error", "finished_at"}


def update_run(db: Database, run_id: str, only_if_running: bool = False, **fields: Any) -> bool:
    bad = set(fields) - _RUN_COLUMNS
    if bad:
        raise ValueError(f"kolom runs tidak dikenal: {sorted(bad)}")
    if not fields:
        return False
    sets = ", ".join(f"{k} = ?" for k in fields)
    guard = " AND status = 'running'" if only_if_running else ""
    with db.write() as conn:
        return conn.execute(f"UPDATE runs SET {sets} WHERE run_id = ?{guard}", (*fields.values(), run_id)).rowcount > 0


def get_run_row(db: Database, run_id: str) -> Optional[sqlite3.Row]:
    with db.read() as conn:
        return conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()


def running_run_for_scope(db: Database, scope: str) -> Optional[str]:
    with db.read() as conn:
        if scope == "global":
            row = conn.execute(
                "SELECT run_id FROM runs WHERE status = 'running' AND run_mode = 'explore' LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT run_id FROM runs WHERE status = 'running' AND run_mode = 'replay' AND session_id = ? LIMIT 1",
                (scope.split(":", 1)[1],),
            ).fetchone()
    return row["run_id"] if row else None


def fail_stale_runs(db: Database, message: str) -> int:
    with db.write() as conn:
        cur = conn.execute(
            "UPDATE runs SET status = 'failed', error = ?, finished_at = ? WHERE status = 'running'",
            (message, now_iso()),
        )
        return cur.rowcount


def list_runs(db: Database, limit: int = 20) -> list[S.RunListItem]:
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
    return [
        S.RunListItem(
            run_id=r["run_id"],
            run_mode=r["run_mode"],
            session_id=r["session_id"],
            brief_id=r["brief_id"],
            n=r["n"],
            use_orchestrator=bool(r["use_orchestrator"]),
            status=r["status"],
            llm_status=r["llm_status"],
            model_version=r["model_version"],
            created_at=r["created_at"],
            finished_at=r["finished_at"],
        )
        for r in rows
    ]


def build_run(db: Database, run_id: str, after_seq: int = 0) -> Optional[S.Run]:
    row = get_run_row(db, run_id)
    if row is None:
        return None
    return S.Run(
        run_id=row["run_id"],
        run_mode=row["run_mode"],
        session_id=row["session_id"],
        brief_id=row["brief_id"],
        specs=_load(row["specs_json"]),
        n=row["n"],
        use_orchestrator=bool(row["use_orchestrator"]),
        status=row["status"],
        llm_status=row["llm_status"],
        model_version=row["model_version"],
        recommendation=row["recommendation"],
        error=row["error"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        candidates=candidates_for_run(db, run_id),
        events=events_after(db, run_id, after_seq),
    )


# candidates

def insert_candidate(db: Database, c: S.Candidate) -> None:
    with db.write() as conn:
        conn.execute(
            "INSERT INTO candidates (candidate_id, run_id, rank, origin, source_record_id, formula_json, prediction_json, "
            "gate_json, evidence_json, summary_json, decision, decision_reason, acknowledged, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                c.candidate_id,
                c.run_id,
                c.rank,
                c.origin,
                c.source_record_id,
                _dump(c.formula),
                _dump(c.prediction) if c.prediction else None,
                _dump(c.gate),
                _dump(c.evidence),
                _dump(c.summary),
                c.decision,
                c.decision_reason,
                int(c.acknowledged),
                None,
            ),
        )


_CANDIDATE_JSON = {"prediction": "prediction_json", "gate": "gate_json", "evidence": "evidence_json", "summary": "summary_json"}
_CANDIDATE_PLAIN = {"decision", "decision_reason", "acknowledged", "decided_at"}


def update_candidate(db: Database, candidate_id: str, **fields: Any) -> None:
    cols: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _CANDIDATE_JSON:
            cols[_CANDIDATE_JSON[key]] = _dump(value) if value is not None else None
        elif key in _CANDIDATE_PLAIN:
            cols[key] = int(value) if key == "acknowledged" else value
        else:
            raise ValueError(f"kolom candidates tidak dikenal: {key}")
    if not cols:
        return
    sets = ", ".join(f"{k} = ?" for k in cols)
    with db.write() as conn:
        conn.execute(f"UPDATE candidates SET {sets} WHERE candidate_id = ?", (*cols.values(), candidate_id))


def _row_to_lab(r: sqlite3.Row) -> S.LabResult:
    return S.LabResult(
        lab_result_id=r["lab_result_id"],
        batch_index=r["batch_index"],
        outputs=_load(r["outputs_json"], {}),
        specs_met=_load(r["specs_met_json"], {}),
        source=r["source"],
        variant=r["variant"],
        recorded_at=r["recorded_at"],
        retrained_model_version=r["retrained_model_version"],
    )


def _row_to_candidate(r: sqlite3.Row, lab: Optional[sqlite3.Row]) -> S.Candidate:
    return S.Candidate(
        candidate_id=r["candidate_id"],
        run_id=r["run_id"],
        rank=r["rank"],
        origin=r["origin"],
        source_record_id=r["source_record_id"],
        formula=_load(r["formula_json"]),
        prediction=_load(r["prediction_json"]),
        gate=_load(r["gate_json"]),
        evidence=_load(r["evidence_json"], []),
        summary=_load(r["summary_json"]),
        decision=r["decision"],
        decision_reason=r["decision_reason"],
        acknowledged=bool(r["acknowledged"]),
        lab_result=_row_to_lab(lab) if lab is not None else None,
    )


def get_candidate(db: Database, candidate_id: str) -> Optional[S.Candidate]:
    with db.read() as conn:
        row = conn.execute("SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if row is None:
            return None
        lab = conn.execute("SELECT * FROM lab_results WHERE candidate_id = ?", (candidate_id,)).fetchone()
    return _row_to_candidate(row, lab)


def candidates_for_run(db: Database, run_id: str) -> list[S.Candidate]:
    with db.read() as conn:
        rows = conn.execute("SELECT * FROM candidates WHERE run_id = ? ORDER BY rank", (run_id,)).fetchall()
        labs = {
            r["candidate_id"]: r
            for r in conn.execute(
                "SELECT l.* FROM lab_results l JOIN candidates c ON c.candidate_id = l.candidate_id WHERE c.run_id = ?",
                (run_id,),
            ).fetchall()
        }
    return [_row_to_candidate(r, labs.get(r["candidate_id"])) for r in rows]


# lab_results

def insert_lab_result(db: Database, candidate_id: str, scope: str, lab: S.LabResult) -> None:
    with db.write() as conn:
        conn.execute(
            "INSERT INTO lab_results (lab_result_id, candidate_id, scope, batch_index, outputs_json, specs_met_json, "
            "source, variant, retrained_model_version, archived, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                lab.lab_result_id,
                candidate_id,
                scope,
                lab.batch_index,
                _dump(lab.outputs),
                _dump(lab.specs_met),
                lab.source,
                lab.variant,
                lab.retrained_model_version,
                lab.recorded_at.isoformat(),
            ),
        )


def set_retrained_version(db: Database, lab_result_id: str, version: str) -> None:
    with db.write() as conn:
        conn.execute("UPDATE lab_results SET retrained_model_version = ? WHERE lab_result_id = ?", (version, lab_result_id))


def active_lab_rows(db: Database, scope: str) -> list[sqlite3.Row]:
    with db.read() as conn:
        return conn.execute(
            "SELECT l.*, c.formula_json FROM lab_results l JOIN candidates c ON c.candidate_id = l.candidate_id "
            "WHERE l.scope = ? AND l.archived = 0 ORDER BY l.batch_index",
            (scope,),
        ).fetchall()


def next_batch_index(db: Database, scope: str) -> int:
    with db.read() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM lab_results WHERE scope = ? AND archived = 0", (scope,)
        ).fetchone()[0] + 1


def archive_scope(db: Database, scope: str) -> int:
    with db.write() as conn:
        return conn.execute("UPDATE lab_results SET archived = 1 WHERE scope = ? AND archived = 0", (scope,)).rowcount


def progress(db: Database, scope: str) -> S.Progress:
    history: list[S.BatchRecord] = []
    best = 0
    hit: Optional[int] = None
    for r in active_lab_rows(db, scope):
        met = _load(r["specs_met_json"], {})
        count = sum(1 for k in S.SPEC_KEYS if met.get(k))
        best = max(best, count)
        if hit is None and met.get("ALL"):
            hit = r["batch_index"]
        history.append(
            S.BatchRecord(
                batch_index=r["batch_index"],
                candidate_id=r["candidate_id"],
                specs_met=met,
                outputs=_load(r["outputs_json"], {}),
            )
        )
    return S.Progress(
        scope=scope,
        batches=len(history),
        hit_at_batch=hit,
        best_specs_met=best,
        total_specs=TOTAL_SPECS,
        history=history,
    )


# agent_events

def add_event(
    db: Database,
    run_id: Optional[str],
    agent: str,
    action: str,
    status: str,
    detail: Optional[dict] = None,
    duration_ms: Optional[int] = None,
) -> S.AgentEvent:
    text = _dump(detail or {})
    if len(text) > 1000:
        text = _dump({"truncated": True, "preview": text[:900]})
    ts = now_iso()
    with db.write() as conn:
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_events WHERE run_id IS ?", (run_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO agent_events (run_id, seq, agent, action, status, detail_json, duration_ms, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, seq, agent, action, status, text, duration_ms, ts),
        )
    return S.AgentEvent(seq=seq, agent=agent, action=action, status=status, detail=_load(text, {}), duration_ms=duration_ms, ts=ts)


def events_after(db: Database, run_id: str, after_seq: int = 0) -> list[S.AgentEvent]:
    with db.read() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_events WHERE run_id = ? AND seq > ? ORDER BY seq", (run_id, after_seq)
        ).fetchall()
    return [
        S.AgentEvent(
            seq=r["seq"],
            agent=r["agent"],
            action=r["action"],
            status=r["status"],
            detail=_load(r["detail_json"], {}),
            duration_ms=r["duration_ms"],
            ts=r["ts"],
        )
        for r in rows
    ]


# replay_sessions

def insert_replay_session(
    db: Database, session_id: str, brief_id: str, seed: int, initial_record_ids: Iterable[str]
) -> None:
    with db.write() as conn:
        conn.execute(
            "INSERT INTO replay_sessions (session_id, brief_id, seed, initial_record_ids, revealed_record_ids, hit_at_batch, created_at) "
            "VALUES (?, ?, ?, ?, '[]', NULL, ?)",
            (session_id, brief_id, int(seed), _dump(list(initial_record_ids)), now_iso()),
        )


def get_replay_session(db: Database, session_id: str) -> Optional[dict]:
    with db.read() as conn:
        r = conn.execute("SELECT * FROM replay_sessions WHERE session_id = ?", (session_id,)).fetchone()
    if r is None:
        return None
    return {
        "session_id": r["session_id"],
        "brief_id": r["brief_id"],
        "seed": r["seed"],
        "initial_record_ids": _load(r["initial_record_ids"], []),
        "revealed_record_ids": _load(r["revealed_record_ids"], []),
        "hit_at_batch": r["hit_at_batch"],
        "created_at": r["created_at"],
    }


def update_replay_session(
    db: Database, session_id: str, revealed_record_ids: list[str], hit_at_batch: Optional[int]
) -> None:
    with db.write() as conn:
        conn.execute(
            "UPDATE replay_sessions SET revealed_record_ids = ?, hit_at_batch = ? WHERE session_id = ?",
            (_dump(revealed_record_ids), hit_at_batch, session_id),
        )


# jobs

def insert_job(db: Database, job: S.Job) -> None:
    with db.write() as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, kind, trigger, status, detail_json, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job.job_id,
                job.kind,
                job.trigger,
                job.status,
                _dump(job.detail),
                job.started_at.isoformat() if job.started_at else None,
                job.finished_at.isoformat() if job.finished_at else None,
            ),
        )


def update_job(db: Database, job_id: str, status: str, detail: Optional[dict] = None, started: bool = False, finished: bool = False) -> None:
    cols: dict[str, Any] = {"status": status}
    if detail is not None:
        cols["detail_json"] = _dump(detail)
    if started:
        cols["started_at"] = now_iso()
    if finished:
        cols["finished_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in cols)
    with db.write() as conn:
        conn.execute(f"UPDATE jobs SET {sets} WHERE job_id = ?", (*cols.values(), job_id))


def _row_to_job(r: sqlite3.Row) -> S.Job:
    return S.Job(
        job_id=r["job_id"],
        kind=r["kind"],
        trigger=r["trigger"],
        status=r["status"],
        detail=_load(r["detail_json"], {}),
        started_at=r["started_at"],
        finished_at=r["finished_at"],
    )


def last_job(db: Database, kind: str) -> Optional[S.Job]:
    with db.read() as conn:
        r = conn.execute("SELECT * FROM jobs WHERE kind = ? ORDER BY rowid DESC LIMIT 1", (kind,)).fetchone()
    return _row_to_job(r) if r else None


def active_job(db: Database, kind: str) -> Optional[S.Job]:
    with db.read() as conn:
        r = conn.execute(
            "SELECT * FROM jobs WHERE kind = ? AND status IN ('queued', 'running') ORDER BY rowid DESC LIMIT 1", (kind,)
        ).fetchone()
    return _row_to_job(r) if r else None
