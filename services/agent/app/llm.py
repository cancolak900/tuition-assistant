"""LLM abstraction used by the agent loop.

The agent keeps a provider-neutral history (list of dicts) and passes it to an `LLM` each round:
    {"role": "user",  "text": "..."}
    {"role": "model", "text": "...", "calls": [ToolCall, ...], "raw": <provider object or None>}
    {"role": "tool",  "results": [ToolResult, ...]}

`GeminiLLM` talks to Gemini with automatic function calling disabled, so every tool call goes back
to the agent, which executes it and records it in the trace. Tests use a scripted fake (tests/fakes.py).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.errors import AppError

logger = logging.getLogger(__name__)

TRANSIENT_CODES = {429, 500, 503, 504}  # overload or per-model quota: retry, then try the fallback model
# Documented placeholder for function calls replayed to a model that did not produce them.
SKIP_SIGNATURE = b"skip_thought_signature_validator"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    call: ToolCall
    output: Any


@dataclass
class LLMTurn:
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None  # provider message to replay as-is (Gemini needs its thought signatures back)
    model: str | None = None  # which model produced raw; a different model cannot reuse its signatures


class LLM(Protocol):
    async def generate(self, system: str, history: list[dict[str, Any]], tools: list[ToolSpec]) -> LLMTurn: ...


class GeminiLLM:
    """Gemini via the google-genai SDK, with manual function calling.

    Temporary failures (overload, quota, timeout) are retried briefly and then sent to the fallback model,
    so a busy free-tier model does not break the demo.
    """

    retry_delays: tuple[float, ...] = (1.0, 2.0)
    cooldown_seconds = 60.0  # a model that hit its quota or timed out is skipped for a while

    def __init__(self, api_key: str, model: str, temperature: float, fallback_model: str = "", timeout_s: float = 25.0) -> None:
        if not api_key:
            raise AppError(503, "LLM_NOT_CONFIGURED", "The assistant is not configured (missing GEMINI_API_KEY).")
        from google import genai  # imported lazily: tests never load the SDK client
        from google.genai import types

        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))
        self.models = [model] + ([fallback_model] if fallback_model and fallback_model != model else [])
        self._temperature = temperature
        self._skip_until: dict[str, float] = {}

    def _cool_down(self, model: str) -> None:
        self._skip_until[model] = time.monotonic() + self.cooldown_seconds

    @staticmethod
    def _contents(history: list[dict[str, Any]], model: str) -> list[Any]:
        from google.genai import types

        contents: list[types.Content] = []
        for msg in history:
            if msg["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=msg["text"])]))
            elif msg["role"] == "model":
                if msg.get("raw") is not None and msg.get("model") == model:
                    contents.append(msg["raw"])
                    continue
                parts = [types.Part(text=msg["text"])] if msg.get("text") else []
                parts += [types.Part(function_call=types.FunctionCall(id=c.id, name=c.name, args=c.args), thought_signature=SKIP_SIGNATURE)
                          for c in msg.get("calls", [])]
                contents.append(types.Content(role="model", parts=parts))
            elif msg["role"] == "tool":
                parts = [
                    types.Part(function_response=types.FunctionResponse(id=r.call.id, name=r.call.name, response={"result": r.output}))
                    for r in msg["results"]
                ]
                contents.append(types.Content(role="user", parts=parts))
        return contents

    async def _call(self, model: str, history: list[dict[str, Any]], config: Any) -> Any:
        """One model with short retries. Returns the response, or raises the last temporary error."""
        import httpx
        from google.genai import errors

        last: Exception | None = None
        for attempt in range(len(self.retry_delays) + 1):
            try:
                return await self._client.aio.models.generate_content(model=model, contents=self._contents(history, model), config=config)
            except errors.APIError as exc:
                logger.warning("Gemini %s failed (attempt %d): %s %s", model, attempt + 1, exc.code, exc.message)
                if exc.code not in TRANSIENT_CODES:
                    raise AppError(503, "LLM_UNAVAILABLE", "The language model is not reachable right now. Please try again later.") from exc
                last = exc
                if exc.code == 429:
                    self._cool_down(model)
                    break  # quota: waiting a second will not help, go to the fallback model
            except httpx.TimeoutException as exc:
                logger.warning("Gemini %s timed out (attempt %d)", model, attempt + 1)
                last = exc
                self._cool_down(model)
                break  # a slow model stays slow; do not spend the whole turn budget on it
            if attempt < len(self.retry_delays):
                await asyncio.sleep(self.retry_delays[attempt])
        raise last or RuntimeError("no attempt was made")

    async def generate(self, system: str, history: list[dict[str, Any]], tools: list[ToolSpec]) -> LLMTurn:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self._temperature,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description, parameters_json_schema=t.parameters) for t in tools
            ])],
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="AUTO")),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response, used = None, None
        last: Exception | None = None
        now = time.monotonic()
        # Models in cool-down go last instead of first (never dropped: a cooled model is better than no answer).
        ordered = sorted(self.models, key=lambda m: self._skip_until.get(m, 0) > now)
        for model in ordered:
            try:
                response, used = await self._call(model, history, config), model
                break
            except AppError:
                raise
            except Exception as exc:  # temporary error after retries: try the next model
                last = exc
        if response is None:
            raise AppError(503, "LLM_BUSY", "The assistant is busy right now. Please try again in a minute.") from last

        candidate = (response.candidates or [None])[0]
        content = candidate.content if candidate is not None else None
        parts = (content.parts if content is not None else None) or []
        calls = [ToolCall(name=p.function_call.name, args=dict(p.function_call.args or {}), id=p.function_call.id)
                 for p in parts if p.function_call is not None]
        text = "".join(p.text for p in parts if p.text and not p.thought).strip()
        return LLMTurn(text=text, calls=calls, raw=content if parts else None, model=used)
