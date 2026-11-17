"""Request/response models. JSON uses camelCase; Python uses snake_case.

Money is a Decimal internally and is always serialized as a string with two decimals ("3000.00"),
so no client ever sees float rounding errors (NFR-09).
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from pydantic.alias_generators import to_camel

CENT = Decimal("0.01")
TERM_REGEX = r"^[0-9]{4}-(FALL|SPRING)$"
STUDENT_NO_REGEX = r"^[A-Za-z0-9]{1,16}$"


def money_str(value: Decimal) -> str:
    return str(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


Money = Annotated[Decimal, PlainSerializer(money_str, return_type=str, when_used="json"), Field(json_schema_extra={"type": "string", "example": "3000.00"})]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------- errors (documentation only; bodies are built in app.errors) ----------

class ErrorDetail(BaseModel):
    code: str = Field(examples=["STUDENT_NOT_FOUND"])
    message: str
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


def error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses=` helper so Swagger documents the common error body."""
    text = {400: "Bad request", 401: "Missing or invalid token", 403: "Not allowed for this user", 404: "Not found",
            409: "Conflict", 422: "Validation error", 429: "Rate limit exceeded (gateway)"}
    return {c: {"model": ErrorResponse, "description": text.get(c, "Error")} for c in codes}


# ---------- auth ----------

class LoginRequest(CamelModel):
    username: str = Field(min_length=1, max_length=64, examples=["s1001"])
    password: str = Field(min_length=1, max_length=128, examples=["Pass1001!"])


class TokenResponse(CamelModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Lifetime in seconds")
    role: str
    student_no: str | None


class MeResponse(CamelModel):
    user_id: int
    username: str
    role: str
    student_no: str | None


# ---------- tuition query ----------

class TermSummary(CamelModel):
    term: str = Field(examples=["2026-FALL"])
    tuition_total: Money
    total_paid: Money
    balance: Money


class PaymentRequest(CamelModel):
    student_no: str = Field(pattern=STUDENT_NO_REGEX, examples=["S1001"])
    term: str = Field(pattern=TERM_REGEX, examples=["2026-FALL"])
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, description="Positive, at most 2 decimals; send it as a string", examples=["500.00"])
    transaction_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$", description="Client-generated idempotency key", examples=["TX-2026-0001"])


class PaymentResponse(CamelModel):
    status: str = Field(examples=["SUCCESS"])
    transaction_id: str
    student_no: str
    term: str
    paid_amount: Money
    total_paid: Money
    remaining_balance: Money
    currency: str


class TuitionSummary(CamelModel):
    student_no: str = Field(examples=["S1001"])
    term: str | None = Field(description="The requested term, or null for the overall total")
    tuition_total: Money
    total_paid: Money
    balance: Money
    currency: str = Field(examples=["USD"])
    terms: list[TermSummary] = Field(description="Per-term breakdown (one item when a term is requested)")


# ---------- admin ----------

CURRENCY_REGEX = r"^[A-Z]{3}$"


class AddTuitionRequest(CamelModel):
    student_no: str = Field(pattern=STUDENT_NO_REGEX, examples=["S1004"])
    term: str = Field(pattern=TERM_REGEX, examples=["2027-SPRING"])
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["3000.00"])
    currency: str = Field("USD", pattern=CURRENCY_REGEX, description="ISO-4217 code", examples=["USD"])


class AddTuitionResponse(CamelModel):
    status: str = Field(description="CREATED or UPDATED", examples=["CREATED"])
    student_no: str
    term: str
    amount: Money
    currency: str
    previous_amount: Money | None = Field(None, description="Only for UPDATED")


class BatchRowError(CamelModel):
    row: int = Field(description="Line number in the CSV file (the header is line 1)")
    student_no: str | None
    code: str
    reason: str


class BatchResponse(CamelModel):
    status: str = Field(description="COMPLETED (no failures), PARTIAL or FAILED (no successes)")
    total_rows: int
    success_count: int
    failure_count: int
    created_count: int
    updated_count: int
    errors: list[BatchRowError]


class UnpaidItem(CamelModel):
    student_no: str
    full_name: str
    tuition_total: Money
    paid: Money
    balance: Money
    currency: str


class UnpaidPage(CamelModel):
    term: str
    items: list[UnpaidItem]
    page: int
    page_size: int
    total_items: int
    total_pages: int
