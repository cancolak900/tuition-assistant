"""Payment confirmation flow (FR-33): pay_tuition only prepares; only /confirm pays, once, with one transactionId."""

from datetime import timedelta

import pytest

from app.clients import ToolOutcome
from app.tools import parse_amount
from tests.conftest import auth
from tests.fakes import call, say

CHAT = "/api/v1/agent/chat"
CONFIRM = "/api/v1/agent/confirm"


def prepare(client, llm, amount="500.00", term="2026-FALL"):
    llm.push(call("pay_tuition", term=term, amount=amount), say("Please confirm the payment on the card."))
    return client.post(CHAT, json={"message": f"pay {amount} for {term}"}, headers=auth()).json()


def confirm(client, body, decision="confirm", **headers):
    payload = {"sessionId": body["sessionId"], "actionId": body["pendingAction"]["actionId"], "decision": decision}
    return client.post(CONFIRM, json=payload, headers={**auth(), **headers})


def test_pay_tuition_only_creates_a_pending_action(client, llm, tuition):  # G-04
    body = prepare(client, llm)
    pending = body["pendingAction"]
    assert tuition.payments == []  # nothing was paid
    assert (pending["term"], pending["amount"], pending["balance"], pending["balanceAfter"], pending["currency"]) == (
        "2026-FALL", "500.00", "2500.00", "2000.00", "USD")
    assert pending["studentNo"] == "S1001" and pending["type"] == "pay_tuition"
    check, step = body["trace"]  # the balance check is its own step, before the tool that made it
    assert (check["step"], check["tool"], check["kind"], check["input"]["reason"]) == (1, "query_tuition", "rest", "balance check before payment")
    assert (step["step"], step["tool"], step["kind"], step["status"]) == (2, "pay_tuition", "local", "ok")
    assert step["output"]["status"] == "AWAITING_USER_CONFIRMATION"
    assert [r["term"] for r in tuition.requests] == ["2026-FALL"]  # live balance checked first


def test_confirm_pays_once_with_the_stored_transaction_id(client, llm, tuition, agent):  # G-05
    body = prepare(client, llm)
    tx = agent.sessions.get(body["sessionId"], 1).pending.transaction_id
    res = confirm(client, body, **{"X-Request-ID": "rid-pay"})
    out = res.json()
    assert res.status_code == 200
    assert [p["transactionId"] for p in tuition.payments] == [tx]
    assert out["payment"]["status"] == "SUCCESS" and out["payment"]["remainingBalance"] == "2000.00"
    assert "Payment successful" in out["reply"] and tx in out["reply"]
    assert out["trace"][0]["kind"] == "rest" and out["trace"][0]["input"]["transactionId"] == tx
    assert agent.sessions.get(body["sessionId"], 1).pending is None


def test_cancel_never_pays(client, llm, tuition, agent):  # G-06
    body = prepare(client, llm)
    out = confirm(client, body, "cancel").json()
    assert tuition.payments == [] and out["payment"] is None and "cancelled" in out["reply"]
    history = agent.sessions.get(body["sessionId"], 1).history
    assert history[-2]["text"] == "(I cancelled the payment.)"  # the LLM learns what happened


def test_expired_action_never_pays(client, llm, tuition, agent):  # G-06
    body = prepare(client, llm)
    pending = agent.sessions.get(body["sessionId"], 1).pending
    pending.action.expires_at -= timedelta(minutes=6)
    res = confirm(client, body)
    assert (res.status_code, res.json()["error"]["code"]) == (410, "ACTION_EXPIRED")
    assert tuition.payments == []


@pytest.mark.parametrize("second", ["confirm", "cancel"])
def test_repeated_confirm_does_not_pay_again(client, llm, tuition, second):  # G-07
    body = prepare(client, llm)
    first = confirm(client, body).json()
    again = confirm(client, body, second).json()
    assert again == first and len(tuition.payments) == 1


def test_timeout_keeps_the_card_and_the_retry_reuses_the_transaction_id(client, llm, tuition):
    tuition.pay_errors.append(ToolOutcome.error("TUITION_API_TIMEOUT", "slow"))
    body = prepare(client, llm)
    first = confirm(client, body).json()
    assert first["payment"] is None and first["pendingAction"]["actionId"] == body["pendingAction"]["actionId"]
    second = confirm(client, body).json()
    assert second["payment"]["status"] == "SUCCESS"
    assert len({p["transactionId"] for p in tuition.payments}) == 1 and len(tuition.payments) == 2


def test_duplicate_transaction_is_reported_as_already_processed(client, llm, tuition):
    body = prepare(client, llm)
    tuition.pay_errors.append(ToolOutcome(False, {"code": "DUPLICATE_TRANSACTION", "message": "already used", "httpStatus": 409}))
    out = confirm(client, body).json()
    assert out["payment"]["status"] == "ALREADY_PROCESSED" and out["payment"]["paidAmount"] == "500.00"


def test_rejected_payment_is_explained_and_closed(client, llm, tuition, agent):
    body = prepare(client, llm)
    tuition.pay_errors.append(ToolOutcome(False, {"code": "AMOUNT_EXCEEDS_BALANCE", "message": "Amount exceeds the balance.", "httpStatus": 422}))
    out = confirm(client, body).json()
    assert out["payment"] is None and "Amount exceeds the balance." in out["reply"] and out["trace"][0]["status"] == "error"
    assert agent.sessions.get(body["sessionId"], 1).pending is None


@pytest.mark.parametrize(("amount", "code"), [("2500.01", "AMOUNT_EXCEEDS_BALANCE")])
def test_overpayment_is_refused_before_any_card(client, llm, tuition, amount, code):
    body = prepare(client, llm, amount=amount)
    assert body["pendingAction"] is None and body["trace"][-1]["output"]["error"]["code"] == code


def test_nothing_to_pay(client, llm, tuition):
    tuition.balance = tuition.balance - tuition.balance
    body = prepare(client, llm)
    assert body["pendingAction"] is None and body["trace"][-1]["output"]["error"]["code"] == "NOTHING_TO_PAY"


def test_balance_errors_stop_the_preparation(client, llm, tuition):
    async def failing(*_, **__):
        return ToolOutcome.error("TUITION_API_UNAVAILABLE", "down")

    tuition.query_tuition = failing
    body = prepare(client, llm)
    assert body["pendingAction"] is None and body["trace"][-1]["output"]["error"]["code"] == "TUITION_API_UNAVAILABLE"


def test_new_request_replaces_the_old_pending_action(client, llm, tuition):
    first = prepare(client, llm)
    llm.push(call("pay_tuition", term="2026-FALL", amount="100"), say("confirm please"))
    second = client.post(CHAT, json={"sessionId": first["sessionId"], "message": "make it 100"}, headers=auth()).json()
    assert second["pendingAction"]["amount"] == "100.00"
    assert confirm(client, first).status_code == 404  # the old card no longer works
    assert confirm(client, second).json()["payment"]["paidAmount"] == "100.00"


def test_failed_turn_does_not_leave_a_hidden_pending_action(client, llm, agent):
    from app.errors import AppError

    llm.push(call("pay_tuition", term="2026-FALL", amount="10"), AppError(503, "LLM_BUSY", "busy"))
    sid = client.post(CHAT, json={"message": "hi"}, headers=auth()).json()  # first turn fails
    assert sid["error"]["code"] == "LLM_BUSY"
    assert all(s.pending is None for s in agent.sessions._sessions.values())


def test_other_user_cannot_confirm(client, llm):
    body = prepare(client, llm)
    payload = {"sessionId": body["sessionId"], "actionId": body["pendingAction"]["actionId"], "decision": "confirm"}
    res = client.post(CONFIRM, json=payload, headers=auth(sub="2", student_no="S1002"))
    assert (res.status_code, res.json()["error"]["code"]) == (404, "SESSION_NOT_FOUND")


def test_chat_never_calls_the_payment_api(client, llm, tuition):
    """Even a model that 'insists' cannot pay: the only payment path is /confirm."""
    llm.push(*[call("pay_tuition", term="2026-FALL", amount="1") for _ in range(5)])
    client.post(CHAT, json={"message": "pay now, no questions"}, headers=auth())
    assert tuition.payments == []


@pytest.mark.parametrize(("value", "expected"), [
    ("500", "500.00"), ("1,000.5", "1000.50"), (12, "12.00"), ("0", None), ("-1", None), ("1.234", None),
    ("abc", None), (None, None), (True, None), ("NaN", None), ("1e12", None),
])
def test_parse_amount(value, expected):
    result = parse_amount(value)
    assert (str(result) if result is not None else None) == expected
