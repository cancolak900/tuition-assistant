"""Tools declared to the LLM and how each one is executed.

Arguments coming from the LLM are validated here before anything is sent to a service.
"""

import inspect
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.clients import POLICY_TOOL, PolicyClient, ToolOutcome, TuitionClient
from app.llm import ToolCall, ToolSpec
from app.schemas import PendingAction
from app.sessions import PendingPayment, Session, utcnow

CENT = Decimal("0.01")

logger = logging.getLogger(__name__)

STUDENT_NO_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")
TERM_RE = re.compile(r"^\d{4}-(FALL|SPRING)$")  # same rule as the Tuition API
MAX_QUERY_CHARS = 500
TRACE_TEXT_CHARS = 300
SCHEMA_RETRY_SECONDS = 60

# search_tuition_policies is replaced by the schema the MCP server publishes (list_tools) once it is reachable.
TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="search_tuition_policies",
        description=(
            "Search the University Tuition Policies document. Use it for deadlines, installments, late fees, "
            "scholarships, refunds and payment methods. Returns the best matching sections with their section "
            "numbers to cite. It never contains a student's personal balance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Short English keywords, even for a question in another language, e.g. 'fall payment deadline'"},
                "top_k": {"type": "integer", "description": "Number of sections to return (1-10, default 3)"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="query_tuition",
        description=(
            "Get the logged-in student's live tuition data: tuition total, total paid and remaining balance, "
            "overall and per term. Leave studentNo empty for the logged-in student."
        ),
        parameters={
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Optional term like 2026-FALL; omit for all terms"},
                "studentNo": {"type": "string", "description": "Optional; defaults to the logged-in student"},
            },
        },
    ),
    ToolSpec(
        name="pay_tuition",
        description=(
            "Prepare a tuition payment for the logged-in student. It does NOT pay: the student must confirm the "
            "payment on screen. Use the balance from query_tuition to choose the amount when the student says 'all'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Term to pay, like 2026-FALL"},
                "amount": {"type": "string", "description": "Amount as a decimal string, e.g. '500.00'"},
            },
            "required": ["term", "amount"],
        },
    ),
]

TOOL_KINDS = {"search_tuition_policies": "mcp", "query_tuition": "rest", "pay_tuition": "local"}


@dataclass
class ToolContext:
    student_no: str
    token: str
    request_id: str | None = None
    session: Session | None = None  # needed by pay_tuition to store the pending payment
    pending_ttl: timedelta = timedelta(minutes=5)
    payment_prepared: bool = False  # set once a payment card was prepared in this turn
    sub_steps: list["SubStep"] = field(default_factory=list)  # service calls a tool makes internally


@dataclass
class SubStep:
    """A call a tool made on its own (e.g. pay_tuition checking the balance); shown as its own trace step."""

    tool: str
    kind: str
    input: dict[str, Any]
    outcome: ToolOutcome
    duration_ms: int


def money(value: Decimal) -> str:
    return str(value.quantize(CENT))


def parse_amount(value: Any) -> Decimal | None:
    """'500', '500.5', 500, '1,000.00' -> Decimal; None if not a positive amount with at most 2 decimals."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0 or amount != amount.quantize(CENT) or amount >= Decimal("1e10"):
        return None
    return amount.quantize(CENT)


@dataclass
class Execution:
    outcome: ToolOutcome
    duration_ms: int
    sub_steps: list[SubStep] = field(default_factory=list)

    @property
    def llm_output(self) -> Any:
        return self.outcome.data if self.outcome.ok else {"error": self.outcome.data}


def shorten(value: Any, limit: int = TRACE_TEXT_CHARS) -> Any:
    """Copy of a tool result for the trace, with long strings cut (the LLM still gets the full text)."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    if isinstance(value, dict):
        return {k: shorten(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [shorten(v, limit) for v in value]
    return value


class ToolExecutor:
    def __init__(self, policies: PolicyClient, tuition: TuitionClient) -> None:
        self.policies = policies
        self.tuition = tuition
        self._policy_spec: ToolSpec | None = None
        self._retry_at = 0.0

    async def specs(self) -> list[ToolSpec]:
        """Tools for the LLM. The policy tool's description and schema come from the MCP server."""
        if self._policy_spec is None and time.monotonic() >= self._retry_at:
            try:
                remote = next((t for t in await self.policies.list_tools() if t.name == POLICY_TOOL), None)
            except Exception as exc:  # MCP down: use the built-in copy and try again later
                logger.warning("MCP list_tools failed, using the built-in schema: %r", exc)
                remote = None
            if remote is not None:
                self._policy_spec = ToolSpec(remote.name, inspect.cleandoc(remote.description) or TOOLS[0].description, remote.input_schema)
                logger.info("Loaded the %s schema from the MCP server", POLICY_TOOL)
            else:
                self._retry_at = time.monotonic() + SCHEMA_RETRY_SECONDS
        return [self._policy_spec or TOOLS[0], *TOOLS[1:]]

    async def run(self, call: ToolCall, ctx: ToolContext) -> Execution:
        ctx.sub_steps = []
        start = time.perf_counter()
        outcome = await self._dispatch(call, ctx)
        return Execution(outcome, int((time.perf_counter() - start) * 1000), list(ctx.sub_steps))

    async def _dispatch(self, call: ToolCall, ctx: ToolContext) -> ToolOutcome:
        args = call.args or {}
        if call.name == "search_tuition_policies":
            return await self._search(args)
        if call.name == "query_tuition":
            return await self._query(args, ctx)
        if call.name == "pay_tuition":
            return await self._prepare_payment(args, ctx)
        return ToolOutcome.error("UNKNOWN_TOOL", f"There is no tool named {call.name!r}.")

    async def _prepare_payment(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        """FR-33: never pays. Checks the live balance and stores a pending payment that only /confirm can execute."""
        term = str(args.get("term") or "").strip().upper()
        if not TERM_RE.match(term):
            return ToolOutcome.error("INVALID_ARGUMENT", "term must look like 2026-FALL or 2026-SPRING.")
        amount = parse_amount(args.get("amount"))
        if amount is None:
            return ToolOutcome.error("INVALID_ARGUMENT", "amount must be a positive number with at most 2 decimals, like 500.00.")
        if ctx.session is None:
            return ToolOutcome.error("NOT_AVAILABLE", "Payments can only be prepared in a chat session.")
        if ctx.payment_prepared:
            # One card per turn: a second one would silently replace the first, which the student never saw.
            return ToolOutcome.error("ONE_PAYMENT_AT_A_TIME", "A payment card was already prepared in this answer. Nothing was prepared "
                                     "for this term. Ask the student to confirm the first payment; the next one can be prepared afterwards.")
        # Payment is always for the logged-in student: the LLM cannot choose another student here.
        start = time.perf_counter()
        live = await self.tuition.query_tuition(ctx.student_no, term, ctx.token, ctx.request_id)
        ctx.sub_steps.append(SubStep("query_tuition", "rest", {"studentNo": ctx.student_no, "term": term, "reason": "balance check before payment"},
                                     live, int((time.perf_counter() - start) * 1000)))
        if not live.ok:
            return live
        balance, currency = Decimal(live.data["balance"]), live.data["currency"]
        if balance <= 0:
            return ToolOutcome.error("NOTHING_TO_PAY", f"There is no open balance for {term}.", balance=money(balance), currency=currency)
        if amount > balance:
            return ToolOutcome.error("AMOUNT_EXCEEDS_BALANCE", "The amount is higher than the remaining balance; overpayment is not allowed.",
                                     balance=money(balance), currency=currency)
        action = PendingAction(
            action_id=uuid.uuid4().hex, student_no=ctx.student_no, term=term, amount=money(amount), currency=currency,
            balance=money(balance), balance_after=money(balance - amount), expires_at=utcnow() + ctx.pending_ttl,
        )
        # A new request replaces an older pending payment; the old actionId stops working.
        ctx.session.pending = PendingPayment(action=action, transaction_id=f"AGT-{uuid.uuid4().hex}")
        ctx.payment_prepared = True
        return ToolOutcome(True, {
            "status": "AWAITING_USER_CONFIRMATION", "actionId": action.action_id, "term": term, "amount": action.amount,
            "currency": currency, "balance": action.balance, "balanceAfter": action.balance_after,
            "expiresInMinutes": int(ctx.pending_ttl.total_seconds() // 60),
            "note": "Nothing has been paid yet. Ask the student to check the details and press Confirm or Cancel on the payment card.",
        })

    async def _search(self, args: dict[str, Any]) -> ToolOutcome:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolOutcome.error("INVALID_ARGUMENT", "query is required.")
        try:
            top_k = max(1, min(10, int(args.get("top_k") or 3)))
        except (TypeError, ValueError):
            top_k = 3
        return await self.policies.search(query[:MAX_QUERY_CHARS], top_k)

    async def _query(self, args: dict[str, Any], ctx: ToolContext) -> ToolOutcome:
        student_no = str(args.get("studentNo") or ctx.student_no).strip().upper()
        term = args.get("term")
        term = str(term).strip().upper() if term else None
        if not STUDENT_NO_RE.match(student_no):
            return ToolOutcome.error("INVALID_ARGUMENT", "studentNo must be letters and digits only, like S1001.")
        if term is not None and not TERM_RE.match(term):
            return ToolOutcome.error("INVALID_ARGUMENT", "term must look like 2026-FALL or 2026-SPRING.")
        # The token decides what is allowed: asking for another student returns 403 from the API.
        return await self.tuition.query_tuition(student_no, term, ctx.token, ctx.request_id)
