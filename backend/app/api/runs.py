from __future__ import annotations

from fastapi import APIRouter, Query, Request

from fp import schemas as S

from .. import repo
from ..deps import get_state, ok
from ..services import runs

router = APIRouter(tags=["run"])


@router.post("/runs", status_code=202, response_model=S.Envelope[S.RunCreated])
def create_run(request: Request, body: S.RunCreate):
    return ok(request, runs.create_run(get_state(request), body))


@router.get("/runs/{run_id}", response_model=S.Envelope[S.Run])
def get_run(request: Request, run_id: str, after_seq: int = Query(0, ge=0)):
    return ok(request, runs.get_run(get_state(request), run_id, after_seq))


@router.get("/runs", response_model=S.Envelope[list[S.RunListItem]])
def list_runs(request: Request, limit: int = Query(20, ge=1, le=200)):
    return ok(request, repo.list_runs(get_state(request).db, limit))
