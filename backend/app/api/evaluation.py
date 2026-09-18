from __future__ import annotations

import re
from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse

from fp import schemas as S

from .. import repo
from ..deps import get_state, ok
from ..errors import not_found

router = APIRouter(tags=["bukti"])

FIGURE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*\.png$")


@router.get("/evaluation", response_model=S.Envelope[dict[str, Any]])
def get_evaluation(request: Request):
    state = get_state(request)
    report = state.evaluation.get()
    if not isinstance(report, dict):
        detail = state.evaluation.error or "artifacts/evaluation.json belum ada"
        raise not_found("EVALUATION_MISSING", f"Hasil evaluasi belum tersedia ({detail}).")
    return ok(request, report)


@router.get(
    "/evaluation/figures/{name}",
    response_class=FileResponse,
    responses={200: {"content": {"image/png": {}}}},
)
def get_figure(request: Request, name: str):
    state = get_state(request)
    path = state.figures_dir / name
    if not FIGURE_NAME.match(name) or not path.is_file():
        raise not_found("FIGURE_NOT_FOUND", f"Figur '{name}' tidak ditemukan.")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.get("/models", response_model=S.Envelope[list[S.ModelVersion]])
def list_models(request: Request, scope: Optional[str] = Query(None, max_length=80)):
    return ok(request, repo.list_model_versions(get_state(request).db, scope or None))
