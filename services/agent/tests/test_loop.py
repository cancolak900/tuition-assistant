"""Function-calling loop: the tool the LLM picks is executed, its result goes back, and every step is traced."""

from datetime import date

import pytest

from app.agent import ROUND_LIMIT_REPLY, trim_history
from app.errors import AppError
from app.prompts import system_prompt
from tests.conftest import auth, make_token
from tests.fakes import call, say

CHAT = "/api/v1/agent/chat"


def chat(client, message="hi", **body):
    return client.post(CHAT, json={"message": message, **body}, headers=auth())


def test_policy_question_runs_the_policy_tool(client, llm, policies):
    llm.push(call("search_tuition_policies", query="fall payment deadline"), say("Fall tuition is due by 15 September (§2.1)."))
    body = chat(client, "When is the fall deadline?").json()
    assert body["reply"] == "Fall tuition is due by 15 September (§2.1)."
    assert policies.queries == [("fall payment deadline", 3)]
    [step] = body["trace"]
    assert (step["step"], step["tool"], step["kind"], step["status"]) == (1, "search_tuition_policies", "mcp", "ok")
    assert step["input"] == {"query": "fall payment deadline"} and isinstance(step["durationMs"], int)
    assert step["output"]["matches"][0]["text"].endswith("…")  # trace copy is shortened ...
    tool_msg = llm.requests[1]["history"][-1]
    assert tool_msg["role"] == "tool" and not tool_msg["results"][0].output["matches"][0]["text"].endswith("…")  # ... the LLM copy is not


def test_tuition_question_uses_the_callers_token_and_student(client, llm, tuition):
    llm.push(call("query_tuition", term="2026-fall"), say("Your balance is 2500.00 USD."))
    res = client.post(CHAT, json={"message": "my balance?"}, headers={**auth(), "X-Request-ID": "rid-7"})
    step = res.json()["trace"][0]
    assert (step["kind"], step["status"], step["output"]["balance"]) == ("rest", "ok", "2500.00")
    [req] = tuition.requests
    assert (req["studentNo"], req["term"], req["requestId"]) == ("S1001", "2026-FALL", "rid-7")
    assert req["token"].count(".") == 2  # the user's own JWT is forwarded


def test_other_students_data_comes_back_as_a_tool_error(client, llm):
    llm.push(call("query_tuition", studentNo="S1002"), say("I can only help with your own account."))
    step = chat(client).json()["trace"][0]
    assert step["status"] == "error" and step["output"]["error"]["code"] == "FORBIDDEN_OTHER_STUDENT"
    assert llm.requests[1]["history"][-1]["results"][0].output["error"]["httpStatus"] == 403


@pytest.mark.parametrize(
    ("name", "args", "code"),
    [("query_tuition", {"term": "fall"}, "INVALID_ARGUMENT"), ("query_tuition", {"studentNo": "../admin"}, "INVALID_ARGUMENT"),
     ("search_tuition_policies", {"query": "  "}, "INVALID_ARGUMENT"), ("drop_table", {}, "UNKNOWN_TOOL"),
     ("pay_tuition", {"term": "2026-FALL", "amount": "-5"}, "INVALID_ARGUMENT"), ("pay_tuition", {"term": "fall", "amount": "5"}, "INVALID_ARGUMENT")],
)
def test_bad_tool_calls_never_reach_a_service(client, llm, tuition, policies, name, args, code):
    llm.push(call(name, **args), say("sorry"))
    step = chat(client).json()["trace"][0]
    assert (step["status"], step["output"]["error"]["code"]) == ("error", code)
    assert tuition.requests == [] and policies.queries == []


def test_top_k_is_clamped(client, llm, policies):
    llm.push(call("search_tuition_policies", query="refund", top_k=99), call("search_tuition_policies", query="refund", top_k="x"), say("ok"))
    chat(client)
    assert [k for _, k in policies.queries] == [10, 3]


def test_several_rounds_are_numbered_in_order(client, llm):
    llm.push(call("search_tuition_policies", query="late fee"), call("query_tuition"), say("combined"))
    body = chat(client, "can I still pay without a late fee?").json()
    assert [(s["step"], s["tool"]) for s in body["trace"]] == [(1, "search_tuition_policies"), (2, "query_tuition")]
    assert body["reply"] == "combined" and len(llm.requests) == 3


def test_round_limit_stops_the_loop(client, llm, agent):
    llm.push(*[call("query_tuition") for _ in range(10)])
    body = chat(client).json()
    assert body["reply"] == ROUND_LIMIT_REPLY
    assert len(body["trace"]) == agent.settings.max_tool_rounds == len(llm.requests)


def test_empty_model_answer_gets_a_fallback(client, llm):
    llm.push(say(""))
    assert chat(client).json()["reply"].startswith("Sorry")


def test_history_is_kept_between_turns(client, llm):
    llm.push(say("first answer"), say("second answer"))
    sid = chat(client, "first").json()["sessionId"]
    chat(client, "second", sessionId=sid)
    history = llm.requests[1]["history"]
    assert [(m["role"], m["text"]) for m in history] == [("user", "first"), ("model", "first answer"), ("user", "second")]


def test_prompt_and_tools_sent_to_the_llm(client, llm):
    chat(client)
    request = llm.requests[0]
    assert "S1001" in request["system"]
    assert request["tools"] == ["search_tuition_policies", "query_tuition", "pay_tuition"]


def test_llm_failure_returns_503_and_leaves_history_untouched(client, llm, agent):
    llm.push(say("hello"), AppError(503, "LLM_BUSY", "busy"))
    sid = chat(client).json()["sessionId"]
    res = chat(client, "again", sessionId=sid)
    assert (res.status_code, res.json()["error"]["code"]) == (503, "LLM_BUSY")
    session = agent.sessions.get(sid, 1)
    assert [m["role"] for m in session.history] == ["user", "model"]


def test_missing_api_key_is_a_clear_503(client, agent):
    agent._llm = None
    agent.settings.gemini_api_key = ""
    res = client.post(CHAT, json={"message": "hi"}, headers={"Authorization": f"Bearer {make_token()}"})
    assert (res.status_code, res.json()["error"]["code"]) == (503, "LLM_NOT_CONFIGURED")


def test_trim_history_never_starts_inside_a_tool_exchange():
    history = [{"role": "user", "text": "a"}, {"role": "model", "text": "", "calls": [1]}, {"role": "tool", "results": []},
               {"role": "model", "text": "b"}, {"role": "user", "text": "c"}, {"role": "model", "text": "d"}]
    assert trim_history(history, 10) is history
    assert trim_history(history, 4) == history[4:]


def test_system_prompt_has_student_and_date():
    text = system_prompt("S1009", date(2026, 11, 17))
    assert "S1009" in text and "2026-11-17" in text


def test_slow_turn_times_out_with_504(client, agent, llm):
    import asyncio

    async def slow(*_):
        await asyncio.sleep(1)

    agent.settings.turn_timeout_seconds = 0.05
    llm.generate = slow
    res = chat(client)
    assert (res.status_code, res.json()["error"]["code"]) == (504, "AGENT_TIMEOUT")
