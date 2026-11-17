"""Shared fixtures. No network, no live LLM: tests build tokens locally and use fakes for the LLM/MCP/REST."""

import os
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

SECRET = "test-secret-that-is-long-enough-for-hs256-signing"
os.environ["JWT_SECRET"] = SECRET
os.environ.setdefault("GEMINI_API_KEY", "")


def make_token(*, sub: str = "1", role: str = "student", student_no: str | None = "S1001", minutes: int = 5, secret: str = SECRET, iss: str = "tuition-auth") -> str:
    now = datetime.now(UTC)
    claims = {"iss": iss, "sub": sub, "username": f"user{sub}", "role": role, "studentNo": student_no, "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(claims, secret, algorithm="HS256")


def auth(**kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(**kwargs)}"}


@pytest.fixture
def llm():
    from tests.fakes import ScriptedLLM

    return ScriptedLLM()


@pytest.fixture
def policies():
    from tests.fakes import FakePolicies

    return FakePolicies()


@pytest.fixture
def tuition():
    from tests.fakes import FakeTuition

    return FakeTuition()


@pytest.fixture
def agent(llm, policies, tuition):
    from app import config
    from app.agent import Agent
    from app.tools import ToolExecutor

    config.get_settings.cache_clear()
    return Agent(config.get_settings(), llm=llm, executor=ToolExecutor(policies, tuition))


@pytest.fixture
def client(agent) -> TestClient:
    from app.main import create_app
    from app.routers import agent as agent_router

    agent_router.get_agent.cache_clear()
    app = create_app()
    app.dependency_overrides[agent_router.get_agent] = lambda: agent
    return TestClient(app)
