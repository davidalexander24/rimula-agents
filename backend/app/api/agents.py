from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from fp import schemas as S

from .. import jobs
from ..deps import get_state, ok

router = APIRouter(tags=["agent"])


@router.post("/agents/{agent}/run", status_code=202, response_model=S.Envelope[S.JobCreated])
def run_agent(request: Request, agent: str):
    return ok(request, jobs.start_job(get_state(request), agent))


@router.get("/agents/status", response_model=S.Envelope[S.AgentsStatus])
def agents_status(request: Request):
    return ok(request, jobs.agents_status(get_state(request)))


@router.get("/market/summary", response_model=S.Envelope[dict[str, Any]])
def market_summary(request: Request):
    return ok(request, jobs.market_summary(get_state(request)))
