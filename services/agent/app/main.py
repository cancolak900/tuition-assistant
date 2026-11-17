"""Agent service entry point. Routes live under /api/v1/agent and are reached through Kong."""

import logging
import time
import uuid

from fastapi import FastAPI, Request

from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import agent

access_log = logging.getLogger("agent.access")


def create_app() -> FastAPI:
    settings = get_settings()
    prefix = settings.api_prefix
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI tuition assistant: Gemini function calling over MCP (policy search) and the Tuition API (via the gateway).",
        docs_url=f"{prefix}/docs",
        redoc_url=None,
        openapi_url=f"{prefix}/openapi.json",
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def request_log(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        access_log.info("request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
                        request_id, request.method, request.url.path, response.status_code, (time.perf_counter() - start) * 1000)
        return response

    app.include_router(agent.router, prefix=prefix)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
