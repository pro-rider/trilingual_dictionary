from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core import ai_guard, obs
from app.core.config import settings
from app.core.exceptions import ApiError
from app.core.validation import safe_validation_handler
from app.services.auth_flow import AuthNotConfigured

logger = logging.getLogger("app.main")

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _requested_host() -> str:
    """Best-effort read of the uvicorn --host actually requested."""
    argv = sys.argv
    for i, arg in enumerate(argv):
        if arg == "--host" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--host="):
            return arg.split("=", 1)[1]
    return os.environ.get("UVICORN_HOST", "")


def warn_if_exposed() -> None:
    """Loud startup warning when the API may be reachable off-box without a secret."""
    host = _requested_host()
    secret_set = bool(ai_guard._shared_secret())
    exposure = not host or host not in _LOOPBACK_HOSTS
    if exposure and not secret_set:
        logger.warning(
            "AI endpoints may be reachable beyond loopback (host=%s) with no "
            "AI_SHARED_SECRET configured. Set AI_SHARED_SECRET or bind 127.0.0.1.",
            host or "unspecified",
        )


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.version)

    warn_if_exposed()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Dictionary images are files on disk (never bundled in the app). Mounted
    # only when the pipeline has produced something, so a fresh checkout runs.
    images_dir = Path(settings.images_dir)
    if images_dir.is_dir():
        app.mount(
            "/static/images", StaticFiles(directory=str(images_dir)), name="images"
        )

    app.include_router(api_router, prefix="/api/v1")

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        """One structured line per request: route, method, status, duration.

        No query string, no body, no client IP — the project rule is that user
        text is never logged. The route template keeps cardinality low enough
        for useful aggregation.
        """
        start = time.perf_counter()
        response = await call_next(request)
        obs.log_event(
            "http_request",
            route=request.scope.get("route").path if request.scope.get("route") else "unmatched",
            method=request.method,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - start) * 1000),
        )
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.message}
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        """Never echo the submitted value: it can be a password or a code."""
        return await safe_validation_handler(request, exc)

    @app.exception_handler(AuthNotConfigured)
    async def auth_not_configured_handler(request: Request, exc: AuthNotConfigured):
        """A missing pepper is a deployment error, not a 500 with a traceback."""
        logger.error("auth is not configured: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "Auth not configured"})


    @app.get("/")
    def root():
        return {"app": settings.app_name, "version": settings.version}

    return app


app = create_app()
