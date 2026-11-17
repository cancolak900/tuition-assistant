"""Fixes from the manual scenario run: one payment card per answer, payment texts in the chat language."""

import pytest

from app.messages import detect_language
from app.prompts import system_prompt
from tests.conftest import auth
from tests.fakes import call, say

CHAT = "/api/v1/agent/chat"
CONFIRM = "/api/v1/agent/confirm"


def test_second_payment_in_one_answer_is_refused(client, llm, tuition, agent):
    """'Pay everything' over two terms used to replace the first card silently; now the second call is refused."""
    llm.push(call("pay_tuition", term="2026-FALL", amount="1300"), call("pay_tuition", term="2027-SPRING", amount="3000"),
             say("Prepared the fall payment; spring comes after you confirm."))
    body = client.post(CHAT, json={"message": "borcumun hepsini öde"}, headers=auth()).json()
    pays = [s for s in body["trace"] if s["tool"] == "pay_tuition"]
    assert [p["status"] for p in pays] == ["ok", "error"]
    assert pays[1]["output"]["error"]["code"] == "ONE_PAYMENT_AT_A_TIME"
    assert body["pendingAction"]["term"] == "2026-FALL"  # the card the student sees is the one that is pending
    assert agent.sessions.get(body["sessionId"], 1).pending.action.term == "2026-FALL"
    assert len([r for r in tuition.requests if r["term"] == "2027-SPRING"]) == 0  # no balance check for the refused one


def test_next_term_can_be_prepared_in_the_next_answer(client, llm):
    llm.push(call("pay_tuition", term="2026-FALL", amount="100"), say("confirm fall"))
    first = client.post(CHAT, json={"message": "pay all"}, headers=auth()).json()
    client.post(CONFIRM, json={"sessionId": first["sessionId"], "actionId": first["pendingAction"]["actionId"], "decision": "confirm"}, headers=auth())
    llm.push(call("pay_tuition", term="2027-SPRING", amount="100"), say("confirm spring"))
    second = client.post(CHAT, json={"sessionId": first["sessionId"], "message": "now spring"}, headers=auth()).json()
    assert second["pendingAction"]["term"] == "2027-SPRING"


@pytest.mark.parametrize(("message", "decision", "expected"), [
    ("Güz borcumdan 100 öde", "confirm", "Ödeme başarılı"),
    ("borcumdan 100 dolar ode", "cancel", "Ödeme iptal edildi"),
    ("Pay 100 for fall", "confirm", "Payment successful"),
])
def test_payment_texts_follow_the_chat_language(client, llm, message, decision, expected):
    llm.push(call("pay_tuition", term="2026-FALL", amount="100"), say("..."))
    body = client.post(CHAT, json={"message": message}, headers=auth()).json()
    out = client.post(CONFIRM, json={"sessionId": body["sessionId"], "actionId": body["pendingAction"]["actionId"], "decision": decision},
                      headers=auth()).json()
    assert out["reply"].startswith(expected)


@pytest.mark.parametrize(("text", "lang"), [
    ("Güz dönemi son taksit ne zaman?", "tr"), ("borcum ne kadar", "tr"), ("odeme yapmak istiyorum", "tr"),
    ("When is the fall deadline?", "en"), ("What is my balance", "en"), ("100", None), ("ok", None),
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_unclear_message_keeps_the_session_language(client, llm, agent):
    llm.push(say("a"), say("b"))
    sid = client.post(CHAT, json={"message": "borcum ne kadar?"}, headers=auth()).json()["sessionId"]
    client.post(CHAT, json={"sessionId": sid, "message": "500"}, headers=auth())
    assert agent.sessions.get(sid, 1).language == "tr"


def test_prompt_has_the_feedback_rules():
    prompt = system_prompt("S1001")
    assert "English keywords" in prompt  # policy search in English for Turkish questions
    assert "installments: eligibility depends on the balance" in prompt  # A3 uses both tools
    assert "One payment card at a time" in prompt


def test_detected_language_is_stated_in_the_prompt(client, llm):
    llm.push(say("..."), say("..."))
    sid = client.post(CHAT, json={"message": "S1002'nin borcu ne?"}, headers=auth()).json()["sessionId"]
    assert "answer in Turkish" in llm.requests[0]["system"]
    client.post(CHAT, json={"sessionId": sid, "message": "What is my balance?"}, headers=auth())
    assert "answer in English" in llm.requests[1]["system"]
