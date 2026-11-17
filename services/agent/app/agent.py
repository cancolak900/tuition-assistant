"""Agent orchestrator: owns sessions and turns a chat message into a reply plus a tool trace.

Loop (manual function calling): send history + tools to the LLM; while it asks for tools (at most
`max_tool_rounds` rounds) run each one, record a trace step and send the results back; then return the text.
"""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from app.clients import PolicyClient, ToolOutcome, TuitionClient
from app.config import Settings
from app.errors import AppError
from app.llm import LLM, GeminiLLM, ToolResult
from app.prompts import system_prompt
from app.schemas import ChatResponse, ConfirmResponse, PaymentResult, PendingAction, TraceStep
from app.security import CurrentUser
from app.sessions import Session, SessionStore
from app.tools import TOOL_KINDS, ToolContext, ToolExecutor, shorten

logger = logging.getLogger(__name__)

ROUND_LIMIT_REPLY = "Sorry, I could not finish this request. Please ask again in a simpler way."
EMPTY_REPLY = "Sorry, I could not produce an answer. Please try again."
RETRYABLE_PAYMENT_ERRORS = {"TUITION_API_TIMEOUT", "TUITION_API_UNAVAILABLE", "HTTP_502", "HTTP_503", "HTTP_504"}


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
            ctx = ToolContext(student_no=user.student_no, token=user.token, request_id=request_id, session=session,
                              pending_ttl=timedelta(minutes=self.settings.pending_action_ttl_minutes))
            turn: list[dict[str, Any]] = [{"role": "user", "text": message}]
            trace: list[TraceStep] = []
            before = session.pending
            try:
                async with asyncio.timeout(self.settings.turn_timeout_seconds):
                    reply = await self._loop(session.history, turn, trace, ctx)
            except TimeoutError as exc:
                session.pending = before  # the user never saw a card for a payment prepared in a failed turn
                raise AppError(504, "AGENT_TIMEOUT", "The assistant took too long to answer. Please try again.") from exc
            except Exception:
                session.pending = before
                raise
            # Only a finished turn is stored: if the LLM call fails, the history stays as it was.
            session.history = trim_history(session.history + turn, self.settings.max_history_messages)
            created = session.pending if session.pending is not before else None
            return ChatResponse(session_id=session.id, reply=reply, trace=trace, pending_action=created.action if created else None)

    async def _loop(self, past: list[dict[str, Any]], turn: list[dict[str, Any]], trace: list[TraceStep], ctx: ToolContext) -> str:
        system = system_prompt(ctx.student_no)
        tools = await self.executor.specs()
        for _ in range(self.settings.max_tool_rounds):
            answer = await self.llm.generate(system, past + turn, tools)
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

    async def confirm(self, user: CurrentUser, session_id: str, action_id: str, decision: str,
                      request_id: str | None = None) -> ConfirmResponse:
        """FR-33: the only place where a payment is executed, and only after an explicit decision=confirm."""
        session = self.sessions.get(session_id, user.user_id)
        async with session.lock:
            done = session.completed_actions.get(action_id)
            if done is not None:  # repeated click or retry: same answer, no second payment
                return done
            pending = session.pending
            if pending is None or pending.action.action_id != action_id:
                raise AppError(404, "ACTION_NOT_FOUND", "There is no pending payment with this id. Ask the assistant again.")
            if pending.expired:
                session.pending = None
                raise AppError(410, "ACTION_EXPIRED", "This payment confirmation expired. Ask the assistant to prepare it again.")
            action = pending.action

            if decision == "cancel":
                session.pending = None
                reply = f"Payment cancelled. Nothing was paid for {action.term}."
                return self._finish(session, action_id, ConfirmResponse(session_id=session.id, reply=reply, trace=[]), "(I cancelled the payment.)")

            step_input = {"studentNo": action.student_no, "term": action.term, "amount": action.amount, "transactionId": pending.transaction_id}
            start = time.perf_counter()
            outcome = await self.executor.tuition.pay_tuition(action.student_no, action.term, action.amount, pending.transaction_id,
                                                              user.token, request_id)
            if not outcome.ok and outcome.data.get("code") == "DUPLICATE_TRANSACTION":
                # Same transactionId already applied (e.g. an earlier attempt timed out after it succeeded): report it, never pay again.
                outcome = await self._already_paid(action, pending.transaction_id, user.token, request_id)
            step = TraceStep(step=1, tool="pay_tuition", kind="rest", input=step_input, output=shorten(outcome.data),
                             status="ok" if outcome.ok else "error", duration_ms=int((time.perf_counter() - start) * 1000))
            logger.info("request_id=%s payment action=%s status=%s", request_id, action_id, step.status)

            if outcome.ok:
                session.pending = None
                payment = PaymentResult.model_validate(outcome.data)
                reply = (f"Payment successful: {payment.paid_amount} {payment.currency} for {payment.term}. "
                         f"Remaining balance: {payment.remaining_balance} {payment.currency}. Transaction id: {payment.transaction_id}.")
                res = ConfirmResponse(session_id=session.id, reply=reply, trace=[step], payment=payment)
                return self._finish(session, action_id, res, "(I confirmed the payment.)")

            code = outcome.data.get("code")
            if code in RETRYABLE_PAYMENT_ERRORS:
                # Result unknown: keep the card. Confirming again reuses the same transactionId, so it cannot pay twice.
                reply = "I could not reach the payment service, so I do not know yet if the payment went through. Press Confirm again; you will not be charged twice."
                return ConfirmResponse(session_id=session.id, reply=reply, trace=[step], pending_action=action)
            session.pending = None
            reply = f"The payment was not made: {outcome.data.get('message') or code}"
            return self._finish(session, action_id, ConfirmResponse(session_id=session.id, reply=reply, trace=[step]), "(I confirmed the payment.)")

    async def _already_paid(self, action: PendingAction, transaction_id: str, token: str, request_id: str | None) -> ToolOutcome:
        live = await self.executor.tuition.query_tuition(action.student_no, action.term, token, request_id)
        if not live.ok:
            return live
        return ToolOutcome(True, {"status": "ALREADY_PROCESSED", "transactionId": transaction_id, "studentNo": action.student_no,
                                  "term": action.term, "paidAmount": action.amount, "totalPaid": live.data["totalPaid"],
                                  "remainingBalance": live.data["balance"], "currency": live.data["currency"]})

    def _finish(self, session: Session, action_id: str, res: ConfirmResponse, user_note: str) -> ConfirmResponse:
        """Remember the outcome (idempotent /confirm) and tell the LLM what happened, so the next answer is consistent."""
        session.completed_actions[action_id] = res
        note = [{"role": "user", "text": user_note}, {"role": "model", "text": res.reply, "calls": [], "raw": None}]
        session.history = trim_history(session.history + note, self.settings.max_history_messages)
        return res
