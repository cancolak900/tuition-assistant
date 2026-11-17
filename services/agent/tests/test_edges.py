"""Edge cases: session expiry, framework errors in the common format, default wiring, duplicate after an outage."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.clients import ToolOutcome
from app.errors import AppError
from app.sessions import SessionStore
from tests.conftest import auth
from tests.fakes import call, say


def test_idle_sessions_expire():
    store = SessionStore(timedelta(minutes=30))
    old = store.get_or_create(None, 1, "S1001")
    old.updated_at -= timedelta(minutes=31)
    store.get_or_create(None, 2, "S1002")  # any access purges expired sessions
    assert len(store) == 1
    with pytest.raises(AppError) as exc:
        store.get(old.id, 1)
    assert exc.value.code == "SESSION_NOT_FOUND"


def test_unknown_route_uses_the_error_format(client):
    res = client.get("/api/v1/agent/nope")
    assert res.status_code == 404 and res.json()["error"]["code"] == "NOT_FOUND"


def test_unexpected_error_is_a_generic_500(agent):
    from app.main import create_app
    from app.routers import agent as agent_router

    async def boom(*_, **__):
        raise RuntimeError("secret internal detail")

    agent.chat = boom
    app = create_app()
    app.dependency_overrides[agent_router.get_agent] = lambda: agent
    res = TestClient(app, raise_server_exceptions=False).post("/api/v1/agent/chat", json={"message": "hi"}, headers=auth())
    assert res.status_code == 500 and res.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in res.text


def test_default_agent_uses_the_configured_gateway_and_mcp():
    from app import config
    from app.routers import agent as agent_router

    config.get_settings.cache_clear()
    agent_router.get_agent.cache_clear()
    built = agent_router.get_agent()
    assert built.executor.tuition.base == "http://kong:8000/api/v1"
    assert built.executor.policies.url == "http://mcp-server:8100/mcp"
    agent_router.get_agent.cache_clear()


def test_duplicate_while_balance_is_unreachable_is_not_reported_as_paid(client, llm, tuition):
    llm.push(call("pay_tuition", term="2026-FALL", amount="10"), say("confirm?"))
    body = client.post("/api/v1/agent/chat", json={"message": "pay 10"}, headers=auth()).json()
    tuition.pay_errors.append(ToolOutcome(False, {"code": "DUPLICATE_TRANSACTION", "message": "used", "httpStatus": 409}))

    async def down(*_, **__):
        return ToolOutcome.error("TUITION_API_UNAVAILABLE", "down")

    tuition.query_tuition = down
    out = client.post("/api/v1/agent/confirm", json={"sessionId": body["sessionId"], "actionId": body["pendingAction"]["actionId"],
                                                      "decision": "confirm"}, headers=auth()).json()
    assert out["payment"] is None and out["pendingAction"] is not None  # unknown: card stays, retry is safe
