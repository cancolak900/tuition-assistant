"""Test doubles: a scripted LLM and in-memory policy / tuition clients (no network)."""

from decimal import Decimal
from typing import Any

from app.clients import ToolOutcome
from app.llm import LLMTurn, ToolCall


def call(name: str, **args: Any) -> LLMTurn:
    """An LLM turn that asks for one tool."""
    return LLMTurn(calls=[ToolCall(name=name, args=args, id=f"call-{name}")])


def say(text: str) -> LLMTurn:
    return LLMTurn(text=text)


class ScriptedLLM:
    """Returns the scripted turns in order (an Exception item is raised). Records what it was sent."""

    def __init__(self, *script: LLMTurn | Exception) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []

    def push(self, *script: LLMTurn | Exception) -> None:
        self.script.extend(script)

    async def generate(self, system: str, history: list[dict[str, Any]], tools: list[Any]) -> LLMTurn:
        self.requests.append({"system": system, "history": list(history), "tools": [t.name for t in tools]})
        if not self.script:
            return say("done")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


POLICY_HIT = {
    "document": "University_Tuition_Policies.md",
    "documentId": "UNI-TUITION-2026-01",
    "matches": [{"section": "2.1", "heading": "Fall term deadline", "text": "Fall tuition is due by 15 September. " * 20, "score": 7.5}],
}


class FakePolicies:
    def __init__(self, outcome: ToolOutcome | None = None) -> None:
        self.outcome = outcome or ToolOutcome(True, POLICY_HIT)
        self.queries: list[tuple[str, int]] = []

    async def list_tools(self):
        raise ConnectionError("no MCP server in unit tests")  # the executor falls back to the built-in schema

    async def search(self, query: str, top_k: int = 3) -> ToolOutcome:
        self.queries.append((query, top_k))
        return self.outcome


class FakeTuition:
    """Mimics the Tuition API rule: a student token can only read its own record."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.payments: list[dict[str, Any]] = []  # every POST /banking/payments attempt
        self.pay_errors: list[ToolOutcome] = []  # scripted failures, used before the real logic
        self.balance = Decimal("2500.00")
        self._applied: set[str] = set()

    async def pay_tuition(self, student_no: str, term: str, amount: str, transaction_id: str, token: str,
                          request_id: str | None = None) -> ToolOutcome:
        self.payments.append({"studentNo": student_no, "term": term, "amount": amount, "transactionId": transaction_id, "token": token})
        if self.pay_errors:
            return self.pay_errors.pop(0)
        if transaction_id in self._applied:
            return ToolOutcome(False, {"code": "DUPLICATE_TRANSACTION", "message": "already used", "httpStatus": 409})
        self._applied.add(transaction_id)
        self.balance -= Decimal(amount)
        return ToolOutcome(True, {"status": "SUCCESS", "transactionId": transaction_id, "studentNo": student_no, "term": term,
                                  "paidAmount": amount, "totalPaid": str(Decimal("5000.00") - self.balance),
                                  "remainingBalance": str(self.balance), "currency": "USD"})

    async def query_tuition(self, student_no: str, term: str | None, token: str, request_id: str | None = None) -> ToolOutcome:
        self.requests.append({"studentNo": student_no, "term": term, "token": token, "requestId": request_id})
        if student_no != "S1001":
            return ToolOutcome(False, {"code": "FORBIDDEN_OTHER_STUDENT", "message": "Students can only access their own records.", "httpStatus": 403})
        return ToolOutcome(True, {"studentNo": "S1001", "term": term, "tuitionTotal": "5000.00", "totalPaid": str(Decimal("5000.00") - self.balance),
                                  "balance": str(self.balance), "currency": "USD", "terms": []})
