"""FastAPI application entry point. Every route is mounted under /api/v1."""

import logging
import time
import uuid

from fastapi import FastAPI, Request

from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import admin, auth, banking, health, mobile

access_log = logging.getLogger("tuition-api.access")


def create_app() -> FastAPI:
    settings = get_settings()
    prefix = settings.api_prefix

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="University tuition query, payment and administration API (v1).",
        docs_url=f"{prefix}/docs",
        redoc_url=None,
        openapi_url=f"{prefix}/openapi.json",
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        """One access-log line per request, tagged with the gateway's X-Request-ID (correlation id)."""
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        access_log.info(
            "request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
            request_id, request.method, request.url.path, response.status_code, (time.perf_counter() - start) * 1000,
        )
        return response

    for module in (health, auth, mobile, banking, admin):
        app.include_router(module.router, prefix=prefix)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
