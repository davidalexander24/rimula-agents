"""SQLite per instance (PRD §14.4). Pemilik: David (B).

Satu koneksi per operasi, `journal_mode=DELETE` dan `busy_timeout=5000` karena DB ada di NFS.
Semua tulis diserialkan lewat `Database.write()` (satu lock tulis per proses).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DDL = """
CREATE TABLE IF NOT EXISTS model_versions (
    version TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    path TEXT NOT NULL,
    n_train INTEGER NOT NULL,
    parent_version TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replay_sessions (
    session_id TEXT PRIMARY KEY,
    brief_id TEXT NOT NULL,
    seed INTEGER NOT NULL,
    initial_record_ids TEXT NOT NULL,
    revealed_record_ids TEXT NOT NULL,
    hit_at_batch INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    run_mode TEXT NOT NULL CHECK (run_mode IN ('explore', 'replay')),
    session_id TEXT REFERENCES replay_sessions(session_id),
    brief_id TEXT NOT NULL,
    specs_json TEXT NOT NULL,
    n INTEGER NOT NULL,
    use_orchestrator INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    llm_status TEXT NOT NULL CHECK (llm_status IN ('not_used', 'ok', 'degraded')),
    model_version TEXT NOT NULL,
    recommendation TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    rank INTEGER NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('explore', 'pool')),
    source_record_id TEXT,
    formula_json TEXT NOT NULL,
    prediction_json TEXT,
    gate_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT NOT NULL,
    decision TEXT CHECK (decision IN ('approved', 'rejected')),
    decision_reason TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS lab_results (
    lab_result_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates(candidate_id),
    scope TEXT NOT NULL,
    batch_index INTEGER NOT NULL,
    outputs_json TEXT NOT NULL,
    specs_met_json TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('virtual_lab', 'historical', 'manual')),
    variant TEXT,
    retrained_model_version TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT REFERENCES runs(run_id),
    seq INTEGER NOT NULL,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    detail_json TEXT,
    duration_ms INTEGER,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('designer_retrain', 'scout_reindex', 'guardian_recheck')),
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'schedule', 'lab_result')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')),
    detail_json TEXT,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON agent_events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_lab_scope_batch ON lab_results(scope, batch_index);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock:
            conn = self.connect()
            try:
                conn.executescript(DDL)
            finally:
                conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._write_lock:
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                conn.execute("COMMIT")
            finally:
                conn.close()

    def ping(self) -> bool:
        try:
            with self.read() as conn:
                conn.execute("SELECT 1 FROM runs LIMIT 1").fetchall()
            return True
        except sqlite3.Error:
            return False
