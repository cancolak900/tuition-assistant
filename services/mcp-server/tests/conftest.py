"""Shared fixtures: a freshly built index for every test session, wired into the server via MCP_INDEX_PATH."""

from pathlib import Path

import pytest

POLICY = Path(__file__).resolve().parents[1] / "data" / "University_Tuition_Policies.md"


@pytest.fixture(scope="session")
def built_index(tmp_path_factory) -> Path:
    from scripts.build_index import main as build_main

    return build_main(["--source", str(POLICY), "--out", str(tmp_path_factory.mktemp("idx") / "policy_index.json")])


@pytest.fixture
def server(built_index, monkeypatch):
    """The app.server module with its index cache pointed at the test index."""
    from app import server as server_module

    monkeypatch.setenv("MCP_INDEX_PATH", str(built_index))
    server_module.get_index.cache_clear()
    yield server_module
    server_module.get_index.cache_clear()
