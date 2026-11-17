"""Admin operations: Add Tuition (FR-07), Batch (FR-08), Unpaid list (FR-09).

Duplicate-handling rules (also in the README):
- The same (studentNo, term) updates the existing record instead of creating a second one.
- An update may not set the amount below what has already been paid (409 AMOUNT_BELOW_PAID).
- The currency of a tuition that already has payments cannot change (409 CURRENCY_CHANGE_NOT_ALLOWED).
- The student must already exist (404 STUDENT_NOT_FOUND); students are not created implicitly.
- Batch: every row follows the same rules; one bad row never rolls back the good rows.
"""

import csv
import io
import math
import re
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Payment, Student, Tuition
from app.schemas import (
    AddTuitionRequest,
    AddTuitionResponse,
    BatchResponse,
    BatchRowError,
    UnpaidItem,
    UnpaidPage,
    money_str,
)
from app.services.tuition import get_student_or_404, paid_per_tuition

ZERO = Decimal("0.00")
CSV_HEADER = ["studentNo", "term", "amount", "currency"]
MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 5_000


# ---------- Add Tuition ----------

def add_tuition(db: Session, body: AddTuitionRequest, *, commit: bool = True) -> AddTuitionResponse:
    get_student_or_404(db, body.student_no)

    # Insert if new; ON CONFLICT avoids a race between two admins creating the same record.
    new_id = db.scalar(
        insert(Tuition)
        .values(student_no=body.student_no, term=body.term, amount=body.amount, currency=body.currency)
        .on_conflict_do_nothing(constraint="uq_tuitions_student_term")
        .returning(Tuition.id)
    )
    if new_id is not None:
        if commit:
            db.commit()
        return AddTuitionResponse(status="CREATED", student_no=body.student_no, term=body.term, amount=body.amount, currency=body.currency)

    tuition = db.scalar(select(Tuition).where(Tuition.student_no == body.student_no, Tuition.term == body.term).with_for_update())
    paid = db.scalar(select(func.coalesce(func.sum(Payment.amount), ZERO)).where(Payment.tuition_id == tuition.id))
    if body.amount < paid:
        raise AppError(409, "AMOUNT_BELOW_PAID", "The new amount is lower than the amount already paid.", {"amount": money_str(body.amount), "paid": money_str(paid)})
    if paid > 0 and body.currency != tuition.currency:
        raise AppError(409, "CURRENCY_CHANGE_NOT_ALLOWED", "The currency cannot change after payments were made.", {"currency": tuition.currency})

    previous = tuition.amount
    tuition.amount, tuition.currency = body.amount, body.currency
    if commit:
        db.commit()
    else:
        db.flush()
    return AddTuitionResponse(status="UPDATED", student_no=body.student_no, term=body.term, amount=body.amount, currency=body.currency, previous_amount=previous)


# ---------- Batch ----------

def _decode(raw: bytes) -> str:
    if not raw:
        raise AppError(400, "INVALID_FILE", "The uploaded file is empty.")
    if len(raw) > MAX_CSV_BYTES:
        raise AppError(400, "FILE_TOO_LARGE", f"The file is larger than {MAX_CSV_BYTES // 1000} KB.")
    if b"\x00" in raw:
        raise AppError(400, "INVALID_FILE", "The file is not a text CSV file.")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError(400, "INVALID_FILE", "The file must be UTF-8 encoded CSV.") from exc


_PATTERN_HINTS = {
    "studentNo": "must contain only letters and digits (e.g. S1004)",
    "term": "must be YYYY-FALL or YYYY-SPRING (e.g. 2027-SPRING)",
    "currency": "must be a 3-letter ISO code in capitals (e.g. USD)",
}


def _first_error(exc: ValidationError) -> tuple[str, str]:
    err = exc.errors()[0]
    field = str(err["loc"][0]) if err.get("loc") else "row"
    message = _PATTERN_HINTS.get(field, err["msg"]) if err.get("type") == "string_pattern_mismatch" else err["msg"]
    return "INVALID_" + re.sub(r"(?<!^)(?=[A-Z])", "_", field).upper(), f"{field}: {message}"


def add_tuition_batch(db: Session, raw: bytes) -> BatchResponse:
    reader = csv.reader(io.StringIO(_decode(raw)))
    header = [h.strip() for h in next(reader, [])]
    if header != CSV_HEADER:
        raise AppError(400, "INVALID_CSV_HEADER", f"The first line must be: {','.join(CSV_HEADER)}", {"found": header})

    errors: list[BatchRowError] = []
    created = updated = total = 0
    for record in reader:
        line = reader.line_num
        if not any(cell.strip() for cell in record):
            continue  # skip blank lines
        total += 1
        if total > MAX_CSV_ROWS:
            raise AppError(400, "TOO_MANY_ROWS", f"At most {MAX_CSV_ROWS} rows per file.")
        student_no = record[0].strip() if record else None
        if len(record) != len(CSV_HEADER):
            errors.append(BatchRowError(row=line, student_no=student_no, code="INVALID_COLUMNS", reason=f"Expected {len(CSV_HEADER)} columns, found {len(record)}."))
            continue
        try:
            body = AddTuitionRequest.model_validate(dict(zip(CSV_HEADER, (c.strip() for c in record), strict=True)))
        except ValidationError as exc:
            code, reason = _first_error(exc)
            errors.append(BatchRowError(row=line, student_no=student_no, code=code, reason=reason))
            continue

        savepoint = db.begin_nested()  # a failing row only rolls back itself
        try:
            result = add_tuition(db, body, commit=False)
            savepoint.commit()
        except AppError as exc:
            savepoint.rollback()
            errors.append(BatchRowError(row=line, student_no=student_no, code=exc.code, reason=exc.message))
            continue
        created += result.status == "CREATED"
        updated += result.status == "UPDATED"

    db.commit()
    success = created + updated
    status = "COMPLETED" if not errors else ("FAILED" if success == 0 else "PARTIAL")
    return BatchResponse(status=status, total_rows=total, success_count=success, failure_count=len(errors), created_count=created, updated_count=updated, errors=errors)


# ---------- Unpaid list ----------

def unpaid_tuitions(db: Session, term: str, page: int, page_size: int) -> UnpaidPage:
    paid = paid_per_tuition()
    paid_amount = func.coalesce(paid.c.paid, ZERO)
    base = (
        select(Tuition.student_no, Student.full_name, Tuition.amount, paid_amount.label("paid"), Tuition.currency)
        .join(Student, Student.student_no == Tuition.student_no)
        .outerjoin(paid, paid.c.tuition_id == Tuition.id)
        .where(Tuition.term == term, Tuition.amount - paid_amount > 0)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(base.order_by(Tuition.student_no).limit(page_size).offset((page - 1) * page_size)).all()
    items = [UnpaidItem(student_no=s, full_name=n, tuition_total=a, paid=p, balance=a - p, currency=c) for s, n, a, p, c in rows]
    return UnpaidPage(term=term, items=items, page=page, page_size=page_size, total_items=total, total_pages=math.ceil(total / page_size))
