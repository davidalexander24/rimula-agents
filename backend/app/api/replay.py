from __future__ import annotations

from fastapi import APIRouter, Request

from fp import schemas as S

from ..deps import get_state, ok
from ..services import replay

router = APIRouter(tags=["replay"])


@router.post("/replay/sessions", response_model=S.Envelope[S.ReplaySession])
def create_session(request: Request, body: S.ReplaySessionCreate):
    return ok(request, replay.create_session(get_state(request), body))


@router.get("/replay/sessions/{session_id}", response_model=S.Envelope[S.ReplaySession])
def get_session(request: Request, session_id: str):
    return ok(request, replay.view(get_state(request), session_id, include_seed=False, include_progress=True))


@router.post("/candidates/{candidate_id}/reveal", response_model=S.Envelope[S.LabTestResponse])
def reveal(request: Request, candidate_id: str):
    return ok(request, replay.reveal(get_state(request), candidate_id))
