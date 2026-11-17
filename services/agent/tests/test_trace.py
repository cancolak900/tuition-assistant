"""FR-35: every turn returns a step-by-step trace and writes the same trace as one JSON log line."""

import json
import logging

import pytest

from app.errors import AppError
from tests.conftest import auth, make_token
from tests.fakes import call, say

CHAT = "/api/v1/agent/chat"
CONFIRM = "/api/v1/agent/confirm"


def trace_records(caplog, event):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "agent.trace" and json.loads(r.getMessage())["event"] == event]


@pytest.fixture(autouse=True)
def _capture(caplog):
    caplog.set_level(logging.INFO, logger="agent.trace")


def test_turn_is_logged_with_steps_reply_and_request_id(client, llm, caplog):
    llm.push(call("search_tuition_policies", query="late fee"), call("query_tuition"), say("Answer (§4.1)."))
    body = client.post(CHAT, json={"message": "late fee?"}, headers={**auth(), "X-Request-ID": "rid-log"}).json()
    [rec] = trace_records(caplog, "chat_turn")
    assert (rec["requestId"], rec["sessionId"], rec["studentNo"]) == ("rid-log", body["sessionId"], "S1001")
    assert rec["rounds"] == 3 and rec["reply"] == "Answer (§4.1)." and isinstance(rec["durationMs"], int)
    assert [(s["step"], s["tool"], s["kind"], s["status"]) for s in rec["steps"]] == [
        (1, "search_tuition_policies", "mcp", "ok"), (2, "query_tuition", "rest", "ok")]
    assert rec["steps"][0]["input"] == {"query": "late fee"}
    assert len(rec["steps"][0]["output"]["matches"][0]["text"]) <= 121  # log copy is shorter than the response copy
    assert [s["tool"] for s in body["trace"]] == [s["tool"] for s in rec["steps"]]


def test_trace_steps_have_every_field(client, llm):
    llm.push(call("query_tuition", term="2026-FALL"), say("ok"))
    [step] = client.post(CHAT, json={"message": "balance"}, headers=auth()).json()["trace"]
    assert set(step) == {"step", "tool", "kind", "input", "output", "status", "durationMs"}


def test_turn_without_tools_has_an_empty_trace(client, llm, caplog):
    llm.push(say("Hello!"))
    assert client.post(CHAT, json={"message": "hi"}, headers=auth()).json()["trace"] == []
    assert trace_records(caplog, "chat_turn")[0]["steps"] == []


def test_failed_turn_is_logged_with_its_error(client, llm, caplog):
    llm.push(call("query_tuition"), AppError(503, "LLM_BUSY", "busy"))
    client.post(CHAT, json={"message": "hi"}, headers=auth())
    [rec] = trace_records(caplog, "chat_turn")
    assert rec["error"] == "LLM_BUSY" and [s["tool"] for s in rec["steps"]] == ["query_tuition"]


def test_token_never_appears_in_logs(client, llm, caplog):
    token = make_token()
    llm.push(call("query_tuition"), say("ok"))
    client.post(CHAT, json={"message": "hi"}, headers={"Authorization": f"Bearer {token}"})
    assert token not in caplog.text and "Bearer" not in caplog.text


def test_forbidden_result_shows_only_the_error_in_the_trace(client, llm):  # G-08
    llm.push(call("query_tuition", studentNo="S1002"), say("I can only show your own account."))
    [step] = client.post(CHAT, json={"message": "S1002?"}, headers=auth()).json()["trace"]
    assert step["output"] == {"error": {"code": "FORBIDDEN_OTHER_STUDENT", "message": "Students can only access their own records.", "httpStatus": 403}}


def test_confirmation_is_logged(client, llm, caplog):
    llm.push(call("pay_tuition", term="2026-FALL", amount="10"), say("confirm?"))
    body = client.post(CHAT, json={"message": "pay 10"}, headers=auth()).json()
    client.post(CONFIRM, json={"sessionId": body["sessionId"], "actionId": body["pendingAction"]["actionId"], "decision": "confirm"},
                headers=auth())
    [turn] = trace_records(caplog, "chat_turn")
    assert turn["pendingActionId"] == body["pendingAction"]["actionId"]
    [rec] = trace_records(caplog, "payment_confirm")
    assert (rec["decision"], rec["paymentStatus"], rec["stillPending"]) == ("confirm", "SUCCESS", False)
    assert rec["steps"][0]["tool"] == "pay_tuition" and rec["steps"][0]["input"]["transactionId"].startswith("AGT-")
