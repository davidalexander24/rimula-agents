from __future__ import annotations

from fastapi import APIRouter, Request

from fp import schemas as S

from ..deps import get_state, ok
from ..errors import unavailable

router = APIRouter(tags=["data"])


@router.get("/briefs", response_model=S.Envelope[list[S.Brief]])
def list_briefs(request: Request):
    state = get_state(request)
    briefs = state.briefs.get()
    if briefs is None:
        raise unavailable("DATA_NOT_READY", f"Data brief belum tersedia ({state.briefs.error}).")
    return ok(request, list(briefs.values()))


@router.get("/palette", response_model=S.Envelope[S.Palette])
def get_palette(request: Request):
    state = get_state(request)
    palette = state.palette.get()
    if palette is None:
        raise unavailable("DATA_NOT_READY", f"Palet bahan belum tersedia ({state.palette.error}).")
    return ok(request, palette)
