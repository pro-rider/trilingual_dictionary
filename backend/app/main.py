from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core import ai_guard
from app.core.config import settings
from app.core.exceptions import ApiError

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

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status_code, content={"detail": exc.message}
        )

    @app.get("/")
    def root():
        return {"app": settings.app_name, "version": settings.version}

    return app


app = create_app()
