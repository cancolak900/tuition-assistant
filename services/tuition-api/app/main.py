"""FastAPI application entry point. Every route is mounted under /api/v1."""

import logging

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import admin, auth, banking, health, mobile


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

    for module in (health, auth, mobile, banking, admin):
        app.include_router(module.router, prefix=prefix)
    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
