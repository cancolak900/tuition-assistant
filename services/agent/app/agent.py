"""Agent orchestrator: owns sessions and turns a chat message into a reply plus a tool trace.

Loop (manual function calling): send history + tools to the LLM; while it asks for tools (at most
`max_tool_rounds` rounds) run each one, record a trace step and send the results back; then return the text.
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any

from app.clients import PolicyClient, TuitionClient
from app.config import Settings
from app.errors import AppError
from app.llm import LLM, GeminiLLM, ToolResult
from app.prompts import system_prompt
from app.schemas import ChatResponse, ConfirmResponse, TraceStep
from app.security import CurrentUser
from app.sessions import SessionStore
from app.tools import TOOL_KINDS, TOOLS, ToolContext, ToolExecutor, shorten

logger = logging.getLogger(__name__)

ROUND_LIMIT_REPLY = "Sorry, I could not finish this request. Please ask again in a simpler way."
EMPTY_REPLY = "Sorry, I could not produce an answer. Please try again."


def trim_history(history: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Keep the last `limit` messages, starting at a user text message (never inside a tool exchange)."""
    if len(history) <= limit:
        return history
    kept = history[-limit:]
    while kept and kept[0]["role"] != "user":
        kept = kept[1:]
    return kept


class Agent:
    def __init__(self, settings: Settings, llm: LLM | None = None, executor: ToolExecutor | None = None) -> None:
        self.settings = settings
        self.sessions = SessionStore(timedelta(minutes=settings.session_ttl_minutes))
        self._llm = llm
        self.executor = executor or ToolExecutor(PolicyClient(settings.mcp_url), TuitionClient(settings.gateway_url))

    @property
    def llm(self) -> LLM:
        if self._llm is None:  # created on first use, so a missing key fails the request, not the startup
            s = self.settings
            self._llm = GeminiLLM(s.gemini_api_key, s.gemini_model, s.llm_temperature, s.gemini_fallback_model, s.llm_timeout_seconds)
        return self._llm

    async def chat(self, user: CurrentUser, session_id: str | None, message: str, request_id: str | None = None) -> ChatResponse:
        session = self.sessions.get_or_create(session_id, user.user_id, user.student_no)
        async with session.lock:  # one turn at a time per session keeps the history consistent
            ctx = ToolContext(student_no=user.student_no, token=user.token, request_id=request_id)
            turn: list[dict[str, Any]] = [{"role": "user", "text": message}]
            trace: list[TraceStep] = []
            try:
                async with asyncio.timeout(self.settings.turn_timeout_seconds):
                    reply = await self._loop(session.history, turn, trace, ctx)
            except TimeoutError as exc:
                raise AppError(504, "AGENT_TIMEOUT", "The assistant took too long to answer. Please try again.") from exc
            # Only a finished turn is stored: if the LLM call fails, the history stays as it was.
            session.history = trim_history(session.history + turn, self.settings.max_history_messages)
            return ChatResponse(session_id=session.id, reply=reply, trace=trace)

    async def _loop(self, past: list[dict[str, Any]], turn: list[dict[str, Any]], trace: list[TraceStep], ctx: ToolContext) -> str:
        system = system_prompt(ctx.student_no)
        for _ in range(self.settings.max_tool_rounds):
            answer = await self.llm.generate(system, past + turn, TOOLS)
            turn.append({"role": "model", "text": answer.text, "calls": answer.calls, "raw": answer.raw, "model": answer.model})
            if not answer.calls:
                return answer.text or EMPTY_REPLY
            results = []
            for call in answer.calls:
                execution = await self.executor.run(call, ctx)
                results.append(ToolResult(call, execution.llm_output))
                trace.append(TraceStep(
                    step=len(trace) + 1, tool=call.name, kind=TOOL_KINDS.get(call.name, "local"), input=dict(call.args or {}),
                    output=shorten(execution.llm_output), status="ok" if execution.outcome.ok else "error", duration_ms=execution.duration_ms,
                ))
                logger.info("request_id=%s tool=%s status=%s duration_ms=%d", ctx.request_id, call.name,
                            "ok" if execution.outcome.ok else "error", execution.duration_ms)
            turn.append({"role": "tool", "results": results})
        logger.warning("request_id=%s tool round limit (%d) reached", ctx.request_id, self.settings.max_tool_rounds)
        turn.append({"role": "model", "text": ROUND_LIMIT_REPLY, "calls": [], "raw": None})
        return ROUND_LIMIT_REPLY

    async def confirm(self, user: CurrentUser, session_id: str, action_id: str, decision: str) -> ConfirmResponse:
        session = self.sessions.get(session_id, user.user_id)
        if session.pending is None or session.pending.get("actionId") != action_id:
            raise AppError(404, "ACTION_NOT_FOUND", "There is no pending action with this id.")
        raise AppError(501, "NOT_IMPLEMENTED", "Payment confirmation is not available yet.")
