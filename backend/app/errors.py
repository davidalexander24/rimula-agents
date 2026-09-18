"""Error API berbentuk envelope (contracts/api.md §2 sampai §3). Pemilik: David (B)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("formulapilot.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def not_found(code: str, message: str) -> ApiError:
    return ApiError(404, code, message)


def conflict(code: str, message: str) -> ApiError:
    return ApiError(409, code, message)


def unprocessable(code: str, message: str) -> ApiError:
    return ApiError(422, code, message)


def unavailable(code: str, message: str) -> ApiError:
    return ApiError(503, code, message)


def _mode(request: Request) -> str:
    state = getattr(request.app.state, "fp", None)
    if state is None:
        return "degraded"
    try:
        return state.mode()
    except Exception:
        return "degraded"


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "req_unknown")


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    body = {"mode": _mode(request), "error": {"code": code, "message": message, "request_id": _request_id(request)}}
    return JSONResponse(status_code=status, content=body)


_HTTP_CODES = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 400: "BAD_REQUEST"}
_HTTP_MESSAGES = {404: "Endpoint tidak ditemukan.", 405: "Metode HTTP tidak diizinkan untuk endpoint ini."}


def _indonesian(err: dict[str, Any]) -> str:
    kind = str(err.get("type", ""))
    ctx = err.get("ctx") or {}
    if kind == "missing":
        return "wajib diisi"
    if kind in ("less_than_equal", "less_than"):
        return f"maksimal {ctx.get('le', ctx.get('lt'))}"
    if kind in ("greater_than_equal", "greater_than"):
        return f"minimal {ctx.get('ge', ctx.get('gt'))}" if kind == "greater_than_equal" else f"harus lebih dari {ctx.get('gt')}"
    if kind == "literal_error":
        return f"harus salah satu dari {ctx.get('expected', '')}".strip()
    if kind in ("int_parsing", "int_type", "float_parsing", "float_type", "int_from_float"):
        return "harus berupa angka"
    if kind in ("bool_parsing", "bool_type"):
        return "harus true atau false"
    if kind in ("string_type", "string_too_short", "string_too_long", "string_pattern_mismatch"):
        return "format teks tidak valid"
    if kind in ("json_invalid", "model_attributes_type", "dict_type"):
        return "body harus berupa objek JSON yang valid"
    if kind in ("tuple_type", "list_type", "too_short", "too_long"):
        return "harus berupa pasangan [min, max]"
    return str(err.get("msg", "tidak valid")).removeprefix("Value error, ")


def _first_validation_message(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return "Request tidak valid."
    err = errors[0]
    loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path"))
    msg = _indonesian(err)
    return f"{loc}: {msg}" if loc else msg


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, "VALIDATION_ERROR", _first_validation_message(exc.errors()))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = _HTTP_MESSAGES.get(exc.status_code, str(exc.detail))
        return error_response(request, exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error request_id=%s path=%s", _request_id(request), request.url.path)
        return error_response(request, 500, "INTERNAL_ERROR", "Terjadi kesalahan di server. Sebutkan request_id saat melapor.")
