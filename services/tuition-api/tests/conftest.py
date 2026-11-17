"""Shared test fixtures.

Tests use a real PostgreSQL 16 started by testcontainers (never SQLite), so Docker must be running.
No cloud services and no live LLM are needed.
"""

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

# Settings are required at import time; give tests safe defaults before the app is imported.
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-hs256-signing")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://unused:unused@127.0.0.1:1/unused")


def _reset_caches() -> None:
    from app import config, db

    config.get_settings.cache_clear()
    db.get_sessionmaker.cache_clear()
    db.get_engine.cache_clear()


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


def alembic_config(database_url: str):
    from pathlib import Path

    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(scope="session")
def migrated_url(postgres_url: str) -> str:
    """The test database with every migration applied (alembic upgrade head)."""
    from alembic import command

    command.upgrade(alembic_config(postgres_url), "head")
    return postgres_url


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):
    """Build a TestClient whose app points at the given database URL."""

    def _make(database_url: str) -> TestClient:
        monkeypatch.setenv("DATABASE_URL", database_url)
        _reset_caches()
        from app.main import create_app

        return TestClient(create_app())

    yield _make
    _reset_caches()


@pytest.fixture
def client(make_client, postgres_url: str) -> TestClient:
    return make_client(postgres_url)
