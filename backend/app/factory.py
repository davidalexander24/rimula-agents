"""Pembuat app FastAPI Rimula Agents (kode: paket fp/, PRD §14.1). Pemilik: David (B).

Test memakai `create_app(settings)` dari sini agar tidak menyentuh instance mana pun (R22).
"""

from __future__ import annotations

import logging
import secrets
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from fp.config import Settings, get_settings

from .api import agents, briefs, candidates, evaluation, health, progress, replay, runs
from .errors import error_response, install_error_handlers, not_found
from .state import AppState

API_PREFIX = "/api/v1"

PLACEHOLDER_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8"><title>Rimula Agents</title></head>
<body style="font-family: system-ui, sans-serif; margin: 3rem;">
<h1>Rimula Agents</h1>
<p>Frontend belum di-build. API tersedia di <a href="api/v1/health">api/v1/health</a> dan dokumentasi di <a href="docs">docs</a>.</p>
</body></html>"""


def _setup_logging(settings: Settings) -> None:
    logger = logging.getLogger("formulapilot")
    logger.setLevel(logging.INFO)
    target = settings.runtime_logs_dir / "api.log"
    for h in list(logger.handlers):
        if getattr(h, "_fp_target", None) == str(target):
            return
        logger.removeHandler(h)
        h.close()
    target.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(target, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler._fp_target = str(target)  # type: ignore[attr-defined]
    logger.addHandler(handler)
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    stream._fp_target = str(target)  # type: ignore[attr-defined]
    logger.addHandler(stream)
    logger.propagate = False


def close_logging(target_dir: Path) -> None:
    logger = logging.getLogger("formulapilot")
    for h in list(logger.handlers):
        if str(getattr(h, "_fp_target", "")).startswith(str(target_dir)):
            logger.removeHandler(h)
            h.close()


class FrontendApp:
    """Sajikan `frontend/dist` bila ada; jika belum di-build, tampilkan halaman placeholder. Dicek per request."""

    def __init__(self, dist: Path) -> None:
        self.dist = dist
        self._static: Optional[StaticFiles] = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and (self.dist / "index.html").is_file():
            if self._static is None:
                self._static = StaticFiles(directory=str(self.dist), html=True, check_dir=False)
            await self._static(scope, receive, send)
            return
        await HTMLResponse(PLACEHOLDER_HTML)(scope, receive, send)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    _setup_logging(settings)
    log = logging.getLogger("formulapilot.api")
    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.startup()
        try:
            yield
        finally:
            state.shutdown()
            close_logging(settings.runtime_dir)

    app = FastAPI(
        title="Rimula Agents API",
        version="1.0",
        root_path=settings.public_root_path,
        lifespan=lifespan,
    )
    app.state.fp = state
    install_error_handlers(app)
    if settings.allowed_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
        log.info("CORS aktif untuk origin: %s", ", ".join(settings.allowed_origins))

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 0 < len(incoming) <= 64 else f"req_{secrets.token_hex(6)}"
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
            response = error_response(request, 500, "INTERNAL_ERROR", "Terjadi kesalahan di server. Sebutkan request_id saat melapor.")
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith(API_PREFIX):
            log.info(
                "%s %s %s %.0fms request_id=%s",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
                request_id,
            )
        return response

    for module in (health, briefs, runs, candidates, replay, progress, evaluation, agents):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.api_route(f"{API_PREFIX}/{{path:path}}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def api_not_found(path: str):
        raise not_found("NOT_FOUND", f"Endpoint tidak ditemukan: {API_PREFIX}/{path}")

    app.mount("/", FrontendApp(settings.frontend_dist), name="ui")
    return app

