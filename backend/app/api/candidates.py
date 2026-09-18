from __future__ import annotations

from fastapi import APIRouter, Request

from fp import schemas as S

from ..deps import get_state, ok
from ..services import candidates, lab

router = APIRouter(tags=["kandidat"])


@router.post("/candidates/{candidate_id}/decision", response_model=S.Envelope[S.Candidate])
def decide(request: Request, candidate_id: str, body: S.DecisionRequest):
    return ok(request, candidates.decide(get_state(request), candidate_id, body))


@router.post("/candidates/{candidate_id}/test", response_model=S.Envelope[S.LabTestResponse])
def test_in_virtual_lab(request: Request, candidate_id: str):
    return ok(request, lab.run_candidate_test(get_state(request), candidate_id))
