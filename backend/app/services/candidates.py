"""Keputusan formulator atas kandidat (PRD §14.5, contracts/api.md §5.3). Pemilik: David (B)."""

from __future__ import annotations

import threading

from fp import schemas as S
from fp.config import now_iso

from .. import repo
from ..errors import conflict, not_found, unprocessable
from ..state import AppState

_decision_lock = threading.Lock()


def get_candidate(state: AppState, candidate_id: str) -> S.Candidate:
    cand = repo.get_candidate(state.db, candidate_id)
    if cand is None:
        raise not_found("CANDIDATE_NOT_FOUND", f"Kandidat '{candidate_id}' tidak ditemukan.")
    return cand


def decide(state: AppState, candidate_id: str, req: S.DecisionRequest) -> S.Candidate:
    with _decision_lock:
        cand = get_candidate(state, candidate_id)
        run = repo.get_run_row(state.db, cand.run_id)
        if run is not None and run["status"] == "running":
            raise conflict("RUN_IN_PROGRESS", "Run kandidat ini masih berjalan. Tunggu sampai selesai sebelum memutuskan.")
        if cand.decision is not None:
            raise conflict("ALREADY_DECIDED", f"Kandidat #{cand.rank} sudah diputuskan ({cand.decision}).")
        reason = req.reason.strip()
        if len(reason) < S.REASON_MIN_LEN:
            raise unprocessable("REASON_REQUIRED", f"Alasan keputusan minimal {S.REASON_MIN_LEN} karakter.")
        if req.decision == "approved":
            if cand.gate.status == "blocked":
                raise conflict("GATE_BLOCKED", "Kandidat diblokir Guardian dan tidak bisa disetujui.")
            if cand.gate.status == "review" and not req.acknowledged:
                raise conflict("ACK_REQUIRED", "Kandidat perlu ditinjau. Centang bahwa peringatan Guardian sudah dibaca.")
        repo.update_candidate(
            state.db,
            candidate_id,
            decision=req.decision,
            decision_reason=reason,
            acknowledged=bool(req.acknowledged),
            decided_at=now_iso(),
        )
    return get_candidate(state, candidate_id)
