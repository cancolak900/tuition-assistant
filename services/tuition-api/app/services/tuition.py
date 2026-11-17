"""Tuition queries: totals, payments and balances (FR-01, FR-03).

balance = tuition amount - sum of payments. It is always computed with Decimal, never stored.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Payment, Student, Tuition
from app.schemas import TermSummary, TuitionSummary

ZERO = Decimal("0.00")
DEFAULT_CURRENCY = "USD"


def term_sort_key(term: str) -> tuple[int, int]:
    """Chronological order: 2026-SPRING < 2026-FALL < 2027-SPRING."""
    year, season = term.split("-")
    return int(year), 0 if season == "SPRING" else 1


def get_student_or_404(db: Session, student_no: str) -> Student:
    student = db.get(Student, student_no)
    if student is None:
        raise AppError(404, "STUDENT_NOT_FOUND", f"Student {student_no} was not found.", {"studentNo": student_no})
    return student


def paid_per_tuition():
    """Subquery: tuition_id -> total paid."""
    return select(Payment.tuition_id, func.sum(Payment.amount).label("paid")).group_by(Payment.tuition_id).subquery()


def get_summary(db: Session, student_no: str, term: str | None = None) -> TuitionSummary:
    get_student_or_404(db, student_no)

    paid = paid_per_tuition()
    query = (
        select(Tuition.term, Tuition.amount, Tuition.currency, func.coalesce(paid.c.paid, ZERO))
        .outerjoin(paid, paid.c.tuition_id == Tuition.id)
        .where(Tuition.student_no == student_no)
    )
    if term is not None:
        query = query.where(Tuition.term == term)
    rows = sorted(db.execute(query).all(), key=lambda r: term_sort_key(r[0]))

    if term is not None and not rows:
        raise AppError(404, "TUITION_NOT_FOUND", f"No tuition for student {student_no} in term {term}.", {"studentNo": student_no, "term": term})

    currencies = {r[2] for r in rows}
    if len(currencies) > 1:
        # Amounts in different currencies are never added together (README assumption).
        raise AppError(409, "MIXED_CURRENCIES", "Tuitions use different currencies; query one term at a time.", {"currencies": sorted(currencies)})

    terms = [TermSummary(term=t, tuition_total=amount, total_paid=p, balance=amount - p) for t, amount, _, p in rows]
    total = sum((t.tuition_total for t in terms), ZERO)
    total_paid = sum((t.total_paid for t in terms), ZERO)
    return TuitionSummary(
        student_no=student_no,
        term=term,
        tuition_total=total,
        total_paid=total_paid,
        balance=total - total_paid,
        currency=currencies.pop() if currencies else DEFAULT_CURRENCY,
        terms=terms,
    )
