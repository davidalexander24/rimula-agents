from __future__ import annotations

import re

from fastapi import APIRouter, Query, Request

from fp import schemas as S

from .. import repo
from ..deps import get_state, ok
from ..errors import not_found, unprocessable
from ..services import training
from ..state import BASE_MODEL_VERSION

router = APIRouter(tags=["progress"])

SCOPE_RE = re.compile(r"^(global|session:rs_[0-9a-f]{12})$")


@router.get("/progress", response_model=S.Envelope[S.Progress])
def get_progress(request: Request, scope: str = Query("global", max_length=40)):
    state = get_state(request)
    if not SCOPE_RE.match(scope):
        raise unprocessable("VALIDATION_ERROR", "scope harus 'global' atau 'session:<session_id>'.")
    if scope != "global" and repo.get_replay_session(state.db, scope.split(":", 1)[1]) is None:
        raise not_found("SESSION_NOT_FOUND", f"Sesi replay '{scope}' tidak ditemukan.")
    return ok(request, repo.progress(state.db, scope))


@router.post("/progress/reset", response_model=S.Envelope[S.Progress])
def reset_progress(request: Request, body: S.ProgressResetRequest):
    state = get_state(request)
    training.reset_global(state, BASE_MODEL_VERSION)
    return ok(request, repo.progress(state.db, body.scope))
