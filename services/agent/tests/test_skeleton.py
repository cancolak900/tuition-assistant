"""Agent service skeleton: auth, sessions, request validation, error format (FR-34 groundwork)."""

import pytest

from tests.conftest import auth

CHAT = "/api/v1/agent/chat"
CONFIRM = "/api/v1/agent/confirm"


def test_health(client):
    assert client.get("/api/v1/agent/health").json() == {"status": "ok"}


def test_chat_creates_and_reuses_a_session(client):
    first = client.post(CHAT, json={"message": "hello"}, headers=auth())
    assert first.status_code == 200
    body = first.json()
    assert set(body) == {"sessionId", "reply", "trace", "pendingAction"}
    again = client.post(CHAT, json={"sessionId": body["sessionId"], "message": "again"}, headers=auth())
    assert again.status_code == 200 and again.json()["sessionId"] == body["sessionId"]


def test_other_users_session_is_not_found(client):
    sid = client.post(CHAT, json={"message": "hi"}, headers=auth(sub="1", student_no="S1001")).json()["sessionId"]
    res = client.post(CHAT, json={"sessionId": sid, "message": "hi"}, headers=auth(sub="2", student_no="S1002"))
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_unknown_session_is_not_found(client):
    res = client.post(CHAT, json={"sessionId": "nope", "message": "hi"}, headers=auth())
    assert (res.status_code, res.json()["error"]["code"]) == (404, "SESSION_NOT_FOUND")


def test_chat_requires_a_token(client):
    res = client.post(CHAT, json={"message": "hi"})
    assert (res.status_code, res.json()["error"]["code"]) == (401, "UNAUTHORIZED")


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [({"minutes": -1}, "TOKEN_EXPIRED"), ({"secret": "x" * 40}, "INVALID_TOKEN"), ({"iss": "someone-else"}, "INVALID_TOKEN")],
    ids=["expired", "forged", "wrong-issuer"],
)
def test_bad_tokens_are_rejected(client, kwargs, code):
    res = client.post(CHAT, json={"message": "hi"}, headers=auth(**kwargs))
    assert (res.status_code, res.json()["error"]["code"]) == (401, code)


@pytest.mark.parametrize("role", ["bank", "admin"])
def test_only_students_can_chat(client, role):
    res = client.post(CHAT, json={"message": "hi"}, headers=auth(role=role, student_no=None))
    assert (res.status_code, res.json()["error"]["code"]) == (403, "FORBIDDEN_ROLE")


@pytest.mark.parametrize("message", ["", "x" * 2001])
def test_message_length_is_validated(client, message):
    res = client.post(CHAT, json={"message": message}, headers=auth())
    assert (res.status_code, res.json()["error"]["code"]) == (422, "VALIDATION_ERROR")


def test_confirm_unknown_action_is_not_found(client):
    sid = client.post(CHAT, json={"message": "hi"}, headers=auth()).json()["sessionId"]
    res = client.post(CONFIRM, json={"sessionId": sid, "actionId": "missing", "decision": "confirm"}, headers=auth())
    assert (res.status_code, res.json()["error"]["code"]) == (404, "ACTION_NOT_FOUND")


def test_confirm_rejects_unknown_decision(client):
    res = client.post(CONFIRM, json={"sessionId": "s", "actionId": "a", "decision": "maybe"}, headers=auth())
    assert res.status_code == 422


def test_request_id_is_echoed(client):
    res = client.get("/api/v1/agent/health", headers={"X-Request-ID": "abc-1"})
    assert res.headers["X-Request-ID"] == "abc-1"


def test_routes_are_versioned(client):
    spec = client.get("/api/v1/agent/openapi.json").json()
    assert all(p.startswith("/api/v1/agent/") for p in spec["paths"])
