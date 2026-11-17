"""Request/response models of the agent API (camelCase JSON)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TraceStep(CamelModel):
    step: int
    tool: str = Field(examples=["query_tuition"])
    kind: Literal["mcp", "rest", "local"] = Field(description="mcp = policy search, rest = Tuition API via gateway, local = handled by the agent")
    input: dict[str, Any]
    output: Any = Field(description="Tool result as sent back to the LLM (long texts are shortened)")
    status: Literal["ok", "error"]
    duration_ms: int


class PendingAction(CamelModel):
    action_id: str
    type: Literal["pay_tuition"] = "pay_tuition"
    student_no: str
    term: str
    amount: str
    currency: str
    balance: str = Field(description="Balance before the payment")
    balance_after: str
    expires_at: datetime


class ChatRequest(CamelModel):
    session_id: str | None = Field(None, max_length=64, description="Omit to start a new conversation")
    message: str = Field(min_length=1, max_length=2000, examples=["When is the Fall payment deadline?"])


class ChatResponse(CamelModel):
    session_id: str
    reply: str
    trace: list[TraceStep]
    pending_action: PendingAction | None = None


class ConfirmRequest(CamelModel):
    session_id: str = Field(max_length=64)
    action_id: str = Field(max_length=64)
    decision: Literal["confirm", "cancel"]


class PaymentResult(CamelModel):
    status: str
    transaction_id: str
    student_no: str
    term: str
    paid_amount: str
    total_paid: str
    remaining_balance: str
    currency: str


class ConfirmResponse(CamelModel):
    session_id: str
    reply: str
    trace: list[TraceStep]
    payment: PaymentResult | None = None
