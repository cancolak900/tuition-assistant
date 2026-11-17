"""Agent test cases G-01..G-09 from docs/03_Test_Plan.md, end to end through the HTTP API with a scripted LLM.

The REST cases use the real TuitionClient; only the network is replaced (httpx.MockTransport), so the
URL, headers and body that would reach Kong are checked as they are sent. No live LLM, MCP or gateway.
"""

import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients import TuitionClient
from app.tools import ToolExecutor
from tests.conftest import auth, make_token
from tests.fakes import call, say

CHAT = "/api/v1/agent/chat"
CONFIRM = "/api/v1/agent/confirm"


class FakeGateway:
    """Stands in for Kong + Tuition API at the HTTP level and records every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.balance = Decimal("2500.00")
        self.applied: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path.startswith("/api/v1/banking/tuition/"):
            student = path.rsplit("/", 1)[1]
            if student != "S1001":
                return httpx.Response(403, json={"error": {"code": "FORBIDDEN_OTHER_STUDENT", "message": "Students can only access their own records.", "details": None}})
            b = str(self.balance)
            return httpx.Response(200, json={"studentNo": "S1001", "term": request.url.params.get("term"), "tuitionTotal": "5000.00",
                                             "totalPaid": str(Decimal("5000.00") - self.balance), "balance": b, "currency": "USD", "terms": []})
        if request.method == "POST" and path == "/api/v1/banking/payments":
            body = json.loads(request.content)
            if body["transactionId"] in self.applied:
                return httpx.Response(409, json={"error": {"code": "DUPLICATE_TRANSACTION", "message": "already used", "details": None}})
            self.applied.add(body["transactionId"])
            self.balance -= Decimal(body["amount"])
            return httpx.Response(201, json={"status": "SUCCESS", "transactionId": body["transactionId"], "studentNo": body["studentNo"],
                                             "term": body["term"], "paidAmount": body["amount"], "totalPaid": str(Decimal("5000.00") - self.balance),
                                             "remainingBalance": str(self.balance), "currency": "USD"})
        return httpx.Response(404, json={"message": "no route"})

    def payments(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def agent(llm, policies, gateway):
    """Same agent as in production, except for the scripted LLM, the policy fake and the network."""
    from app import config
    from app.agent import Agent

    config.get_settings.cache_clear()
    settings = config.get_settings()
    tuition = TuitionClient(settings.gateway_url, transport=httpx.MockTransport(gateway))
    return Agent(settings, llm=llm, executor=ToolExecutor(policies, tuition))


def chat(client: TestClient, message: str, token: str | None = None, **body) -> dict:
    res = client.post(CHAT, json={"message": message, **body}, headers={"Authorization": f"Bearer {token or make_token()}"})
    assert res.status_code == 200, res.text
    return res.json()


def decide(client: TestClient, body: dict, decision: str = "confirm"):
    payload = {"sessionId": body["sessionId"], "actionId": body["pendingAction"]["actionId"], "decision": decision}
    return client.post(CONFIRM, json=payload, headers=auth())


def prepare(client, llm, amount="500.00"):
    llm.push(call("pay_tuition", term="2026-FALL", amount=amount), say("Please confirm on the card."))
    return chat(client, f"pay {amount} for fall")


def test_g01_policy_tool_goes_to_mcp(client, llm, policies, gateway):
    """G-01: the LLM requests search_tuition_policies -> MCP client called, 1 MCP step, final text returned."""
    llm.push(call("search_tuition_policies", query="fall deadline"), say("Fall tuition is due by 15 September (§2.1)."))
    body = chat(client, "When is the fall deadline?")
    assert policies.queries == [("fall deadline", 3)] and gateway.requests == []
    assert [(s["tool"], s["kind"], s["status"]) for s in body["trace"]] == [("search_tuition_policies", "mcp", "ok")]
    assert body["reply"] == "Fall tuition is due by 15 September (§2.1)."


def test_g02_tuition_tool_calls_the_gateway_with_the_users_jwt(client, llm, gateway, agent):
    """G-02: the LLM requests query_tuition -> REST client called with the user's JWT and the gateway base URL."""
    token = make_token()
    llm.push(call("query_tuition", term="2026-FALL"), say("Your balance is 2500.00 USD."))
    body = chat(client, "my balance?", token=token)
    [req] = gateway.requests
    assert str(req.url) == f"{agent.settings.gateway_url}/api/v1/banking/tuition/S1001?term=2026-FALL"
    assert req.headers["Authorization"] == f"Bearer {token}"  # the caller's own token, not a service credential
    assert body["trace"][0]["output"]["balance"] == "2500.00"


def test_g03_both_tools_are_traced_in_order(client, llm):
    """G-03: the LLM requests both tools -> the trace has 2 steps in order."""
    llm.push(call("search_tuition_policies", query="late fee"), call("query_tuition"), say("Combined answer."))
    body = chat(client, "Can I pay without a late fee?")
    assert [(s["step"], s["tool"], s["kind"]) for s in body["trace"]] == [(1, "search_tuition_policies", "mcp"), (2, "query_tuition", "rest")]


def test_g04_pay_tuition_returns_a_pending_action_and_no_payment(client, llm, gateway):
    """G-04: the LLM requests pay_tuition -> no REST payment call; a pendingAction is returned."""
    body = prepare(client, llm)
    assert gateway.payments() == []
    assert [r.method for r in gateway.requests] == ["GET"]  # only the balance check
    assert body["pendingAction"]["amount"] == "500.00" and body["pendingAction"]["balanceAfter"] == "2000.00"


def test_g05_confirm_pays_once_with_the_stored_transaction_id(client, llm, gateway, agent):
    """G-05: /confirm with confirm -> the payment is called once with the stored transactionId."""
    body = prepare(client, llm)
    stored = agent.sessions.get(body["sessionId"], 1).pending.transaction_id
    out = decide(client, body).json()
    assert gateway.payments() == [{"studentNo": "S1001", "term": "2026-FALL", "amount": "500.00", "transactionId": stored}]
    assert out["payment"]["status"] == "SUCCESS" and out["payment"]["remainingBalance"] == "2000.00"


@pytest.mark.parametrize("case", ["cancel", "expired"])
def test_g06_cancel_or_expired_never_pays(client, llm, gateway, agent, case):
    """G-06: /confirm with cancel or an expired action -> no payment call."""
    body = prepare(client, llm)
    if case == "expired":
        agent.sessions.get(body["sessionId"], 1).pending.action.expires_at -= timedelta(minutes=10)
        res = decide(client, body, "confirm")
        assert (res.status_code, res.json()["error"]["code"]) == (410, "ACTION_EXPIRED")
    else:
        assert decide(client, body, "cancel").json()["payment"] is None
    assert gateway.payments() == []


def test_g07_repeated_confirm_creates_no_second_payment(client, llm, gateway):
    """G-07: /confirm repeated twice -> the second call does not create a new payment."""
    body = prepare(client, llm)
    first, second = decide(client, body).json(), decide(client, body).json()
    assert first == second and len(gateway.payments()) == 1 and gateway.balance == Decimal("2000.00")


def test_g08_forbidden_is_passed_to_the_llm_without_leaking(client, llm, gateway):
    """G-08: the REST tool returns 403 -> the error goes to the LLM; nothing is leaked in the trace output."""
    llm.push(call("query_tuition", studentNo="S1002"), say("I can only help with your own account."))
    body = chat(client, "What does S1002 owe?")
    [step] = body["trace"]
    assert step["status"] == "error"
    assert step["output"] == {"error": {"code": "FORBIDDEN_OTHER_STUDENT", "message": "Students can only access their own records.", "httpStatus": 403}}
    sent_back = llm.requests[1]["history"][-1]["results"][0].output
    assert sent_back["error"]["code"] == "FORBIDDEN_OTHER_STUDENT"
    assert "balance" not in json.dumps(body) and body["reply"] == "I can only help with your own account."


def test_g09_round_limit_stops_with_a_safe_message(client, llm, agent, gateway):
    """G-09: the tool-round limit is exceeded -> stops after 5 rounds with a safe message."""
    llm.push(*[call("query_tuition") for _ in range(20)])
    body = chat(client, "loop forever")
    assert agent.settings.max_tool_rounds == 5
    assert len(llm.requests) == 5 and len(body["trace"]) == 5 and len(gateway.requests) == 5
    assert body["reply"].startswith("Sorry, I could not finish") and body["pendingAction"] is None
