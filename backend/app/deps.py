"""Helper endpoint: akses state dan envelope sukses. Pemilik: David (B)."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from fp.io_utils import to_jsonable

from .state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.fp


def ok(request: Request, data: Any) -> dict[str, Any]:
    return {"mode": get_state(request).mode(), "data": to_jsonable(data)}
