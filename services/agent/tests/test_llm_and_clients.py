"""Gemini adapter (no network: the SDK call is replaced) and the REST / MCP clients."""

import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors, types

from app.clients import TuitionClient
from app.errors import AppError
from app.llm import GeminiLLM, ToolCall, ToolResult
from app.tools import TOOLS

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def gemini_with(handler, fallback: str = "") -> GeminiLLM:
    llm = GeminiLLM("test-key", "gemini-test", 0.2, fallback)
    llm.retry_delays = (0, 0)
    llm._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=handler)))
    return llm


def response(*parts: types.Part) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])


async def test_gemini_returns_tool_calls_and_disables_automatic_calling():
    seen = {}

    async def handler(*, model, contents, config):
        seen.update(model=model, contents=contents, config=config)
        return response(types.Part(text="thinking", thought=True),
                        types.Part(function_call=types.FunctionCall(id="c1", name="query_tuition", args={"term": "2026-FALL"})))

    turn = await gemini_with(handler).generate("system", [{"role": "user", "text": "balance?"}], TOOLS)
    assert turn.calls == [ToolCall(name="query_tuition", args={"term": "2026-FALL"}, id="c1")]
    assert turn.text == "" and turn.raw is not None
    config = seen["config"]
    assert seen["model"] == "gemini-test" and config.automatic_function_calling.disable is True
    assert [f.name for f in config.tools[0].function_declarations] == [t.name for t in TOOLS]
    assert config.system_instruction == "system" and config.temperature == 0.2


async def test_gemini_history_conversion_replays_raw_model_turns():
    raw = types.Content(role="model", parts=[types.Part(text="kept as is")])
    captured = {}

    async def handler(*, model, contents, config):
        captured["contents"] = contents
        return response(types.Part(text="Final answer."))

    c = ToolCall(name="search_tuition_policies", args={"query": "x"}, id="c9")
    history = [{"role": "user", "text": "q"}, {"role": "model", "text": "", "calls": [c], "raw": None},
               {"role": "tool", "results": [ToolResult(c, {"matches": []})]}, {"role": "model", "text": "a", "calls": [], "raw": raw}]
    history[-1]["model"] = "gemini-test"
    turn = await gemini_with(handler).generate("s", history, TOOLS)
    assert turn.text == "Final answer." and turn.calls == [] and turn.model == "gemini-test"
    user, model, tool, replayed = captured["contents"]
    assert model.parts[0].function_call.name == "search_tuition_policies"
    assert tool.role == "user" and tool.parts[0].function_response.response == {"result": {"matches": []}}
    assert tool.parts[0].function_response.id == "c9" and replayed is raw


async def test_gemini_empty_candidate_is_an_empty_turn():
    async def handler(**_):
        return types.GenerateContentResponse(candidates=[])

    turn = await gemini_with(handler).generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert (turn.text, turn.calls, turn.raw) == ("", [], None)


@pytest.mark.parametrize(("status", "code"), [(429, "LLM_BUSY"), (503, "LLM_BUSY"), (500, "LLM_BUSY"), (400, "LLM_UNAVAILABLE")])
async def test_gemini_errors_become_503(status, code):
    async def handler(**_):
        raise errors.APIError(status, {"error": {"code": status, "message": "nope", "status": "X"}})

    with pytest.raises(AppError) as exc:
        await gemini_with(handler).generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert (exc.value.status_code, exc.value.code) == (503, code)


async def test_gemini_retries_a_temporary_overload():
    attempts = []

    async def handler(**_):
        attempts.append(1)
        if len(attempts) < 3:
            raise errors.APIError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})
        return response(types.Part(text="ok"))

    turn = await gemini_with(handler).generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert turn.text == "ok" and len(attempts) == 3


async def test_busy_model_falls_back_and_rebuilds_foreign_turns():
    used = []
    raw = types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="query_tuition", args={}), thought_signature=b"sig")])

    async def handler(*, model, contents, config):
        used.append(model)
        if model == "gemini-test":
            raise errors.APIError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
        used.append(contents[1])
        return response(types.Part(text="from fallback"))

    c = ToolCall(name="query_tuition", args={})
    history = [{"role": "user", "text": "q"}, {"role": "model", "text": "", "calls": [c], "raw": raw, "model": "gemini-test"},
               {"role": "tool", "results": [ToolResult(c, {})]}]
    turn = await gemini_with(handler, fallback="gemini-lite").generate("s", history, TOOLS)
    assert (turn.text, turn.model) == ("from fallback", "gemini-lite")
    assert used[0] == "gemini-test" and used[1] == "gemini-lite"  # 429: no retry on the same model
    rebuilt = used[2]
    assert rebuilt is not raw and rebuilt.parts[0].thought_signature == b"skip_thought_signature_validator"


async def test_timeout_goes_to_the_fallback_model():
    async def handler(*, model, contents, config):
        if model == "gemini-test":
            raise httpx.ReadTimeout("slow")
        return response(types.Part(text="lite answer"))

    turn = await gemini_with(handler, fallback="gemini-lite").generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert turn.model == "gemini-lite"


@pytest.mark.filterwarnings("ignore")
def test_gemini_needs_a_key():
    with pytest.raises(AppError) as exc:
        GeminiLLM("", "m", 0.2)
    assert exc.value.code == "LLM_NOT_CONFIGURED"


# ---------- REST client (through the gateway) ----------

def tuition_client(handler) -> TuitionClient:
    return TuitionClient("http://kong:8000/", transport=httpx.MockTransport(handler))


async def test_query_tuition_sends_token_term_and_request_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(200, json={"balance": "10.00"})

    out = await tuition_client(handler).query_tuition("S1001", "2026-FALL", "tok", "rid-1")
    req = seen["request"]
    assert out.ok and out.data == {"balance": "10.00"}
    assert str(req.url) == "http://kong:8000/api/v1/banking/tuition/S1001?term=2026-FALL"
    assert req.headers["Authorization"] == "Bearer tok" and req.headers["X-Request-ID"] == "rid-1"


@pytest.mark.parametrize(
    ("res", "expected"),
    [(httpx.Response(403, json={"error": {"code": "FORBIDDEN_OTHER_STUDENT", "message": "own only"}}), ("FORBIDDEN_OTHER_STUDENT", 403)),
     (httpx.Response(401, json={"message": "Unauthorized"}), ("HTTP_401", 401)),
     (httpx.Response(502, text="bad gateway"), ("HTTP_502", 502))],
    ids=["api-error", "kong-error", "not-json"],
)
async def test_query_tuition_errors_are_readable(res, expected):
    out = await tuition_client(lambda _: res).query_tuition("S1001", None, "tok")
    assert not out.ok and (out.data["code"], out.data["httpStatus"]) == expected and out.data["message"]


async def test_query_tuition_network_failure():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    out = await tuition_client(handler).query_tuition("S1001", None, "tok")
    assert (out.ok, out.data["code"]) == (False, "TUITION_API_UNAVAILABLE")


async def test_query_tuition_timeout_is_not_reported_as_a_result():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    out = await tuition_client(handler).query_tuition("S1001", None, "tok")
    assert (out.ok, out.data["code"]) == (False, "TUITION_API_TIMEOUT")


async def test_pay_tuition_posts_the_payment_with_its_transaction_id():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["request"] = request
        return httpx.Response(201, json={"status": "SUCCESS", "transactionId": "tx-1"})

    out = await tuition_client(handler).pay_tuition("S1001", "2026-FALL", "500.00", "tx-1", "tok", "rid-2")
    req = seen["request"]
    assert out.ok and out.data["status"] == "SUCCESS"
    assert (req.method, str(req.url)) == ("POST", "http://kong:8000/api/v1/banking/payments")
    assert json.loads(req.content) == {"studentNo": "S1001", "term": "2026-FALL", "amount": "500.00", "transactionId": "tx-1"}
    assert req.headers["Authorization"] == "Bearer tok"


async def test_api_error_details_are_kept():
    res = httpx.Response(422, json={"error": {"code": "AMOUNT_EXCEEDS_BALANCE", "message": "too much", "details": {"balance": "100.00"}}})
    out = await tuition_client(lambda _: res).pay_tuition("S1001", "2026-FALL", "500.00", "tx", "tok")
    assert out.data == {"code": "AMOUNT_EXCEEDS_BALANCE", "message": "too much", "httpStatus": 422, "details": {"balance": "100.00"}}

async def test_model_out_of_quota_is_skipped_on_the_next_call():
    used = []

    async def handler(*, model, contents, config):
        used.append(model)
        if model == "gemini-test":
            raise errors.APIError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
        return response(types.Part(text="ok"))

    llm = gemini_with(handler, fallback="gemini-lite")
    await llm.generate("s", [{"role": "user", "text": "q"}], TOOLS)
    await llm.generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert used == ["gemini-test", "gemini-lite", "gemini-lite"]  # no wasted call on the second turn


async def test_deadline_exceeded_moves_on_without_retrying_the_same_model():
    """504 DEADLINE_EXCEEDED took ~25 s per attempt; three attempts used to exceed the 80 s turn limit."""
    used = []

    async def handler(*, model, contents, config):
        used.append(model)
        if model == "gemini-test":
            raise errors.APIError(504, {"error": {"code": 504, "message": "Deadline expired", "status": "DEADLINE_EXCEEDED"}})
        return response(types.Part(text="ok"))

    llm = gemini_with(handler, fallback="gemini-lite")
    turn = await llm.generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert (turn.text, turn.model) == ("ok", "gemini-lite")
    assert used == ["gemini-test", "gemini-lite"]
    await llm.generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert used[-1] == "gemini-lite"  # the slow model waits at the back of the queue


async def test_retired_model_404_is_skipped_instead_of_failing_the_turn():
    used = []

    async def handler(*, model, contents, config):
        used.append(model)
        if model == "gemini-old":
            raise errors.APIError(404, {"error": {"code": 404, "message": "no longer available", "status": "NOT_FOUND"}})
        return response(types.Part(text="ok"))

    llm = GeminiLLM("test-key", "gemini-old", 0.2, "gemini-new")
    llm.retry_delays = (0, 0)
    llm._client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=handler)))
    turn = await llm.generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert (turn.text, used) == ("ok", ["gemini-old", "gemini-new"])


async def test_slow_overload_is_not_retried_on_the_same_model():
    used = []

    async def handler(*, model, contents, config):
        used.append(model)
        if model == "gemini-test":
            raise errors.APIError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})
        return response(types.Part(text="ok"))

    llm = gemini_with(handler, fallback="gemini-lite")
    llm.slow_attempt_seconds = 0  # every failure counts as slow
    turn = await llm.generate("s", [{"role": "user", "text": "q"}], TOOLS)
    assert turn.text == "ok" and used == ["gemini-test", "gemini-lite"]


def test_fallback_list_is_tried_in_order_without_duplicates():
    llm = GeminiLLM("test-key", "gemini-a", 0.2, " gemini-b, gemini-a ,gemini-c,")
    assert llm.models == ["gemini-a", "gemini-b", "gemini-c"]
