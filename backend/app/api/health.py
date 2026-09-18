from __future__ import annotations

from fastapi import APIRouter, Request

from fp import schemas as S

from ..deps import get_state, ok

router = APIRouter(tags=["sistem"])


@router.get("/health", response_model=S.Envelope[S.Health])
def health(request: Request):
    return ok(request, get_state(request).health())
