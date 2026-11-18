"""Pay Tuition (FR-04..FR-06, NFR-08).

Safety rules:
- The tuition row is locked (SELECT ... FOR UPDATE) for the whole transaction, so two concurrent
  payments for the same tuition are serialized and can never overdraw the balance.
- transaction_id is unique in the database. A repeated id returns 409 and changes nothing, so a
  client (or the agent) can retry safely with the same id.
- The 409 details (student, term, paid amount of the earlier payment) are only shown to callers who
  may see that payment: the bank, or the student who owns it. Anyone else gets the code without
  details, so a guessed transactionId reveals nothing about another student's payment.
- Overpayment is not supported: amount must be > 0 and <= the current balance.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Payment, Tuition
from app.schemas import PaymentRequest, PaymentResponse, money_str
from app.security import ROLE_BANK, ROLE_STUDENT, CurrentUser
from app.services.tuition import get_student_or_404

ZERO = Decimal("0.00")


def _duplicate(db: Session, user: CurrentUser, existing: Payment) -> AppError:
    owner = db.get(Tuition, existing.tuition_id)  # the tuition the earlier payment belongs to
    visible = user.role == ROLE_BANK or (owner is not None and owner.student_no == user.student_no)
    details = (
        {"transactionId": existing.transaction_id, "studentNo": owner.student_no, "term": owner.term, "paidAmount": money_str(existing.amount)}
        if visible
        else None
    )
    return AppError(409, "DUPLICATE_TRANSACTION", "This transactionId was already used; the payment was not applied again.", details)


def _paid_total(db: Session, tuition_id: int) -> Decimal:
    return db.scalar(select(func.coalesce(func.sum(Payment.amount), ZERO)).where(Payment.tuition_id == tuition_id))


def pay_tuition(db: Session, user: CurrentUser, body: PaymentRequest) -> PaymentResponse:
    get_student_or_404(db, body.student_no)

    existing = db.scalar(select(Payment).where(Payment.transaction_id == body.transaction_id))
    if existing is not None:
        raise _duplicate(db, user, existing)

    tuition = db.scalar(
        select(Tuition).where(Tuition.student_no == body.student_no, Tuition.term == body.term).with_for_update()
    )
    if tuition is None:
        raise AppError(404, "TUITION_NOT_FOUND", f"No tuition for student {body.student_no} in term {body.term}.", {"studentNo": body.student_no, "term": body.term})

    balance = tuition.amount - _paid_total(db, tuition.id)
    if body.amount > balance:
        db.rollback()
        raise AppError(
            422,
            "AMOUNT_EXCEEDS_BALANCE",
            "The amount is greater than the remaining balance.",
            {"amount": money_str(body.amount), "balance": money_str(balance), "currency": tuition.currency},
        )

    payment = Payment(
        transaction_id=body.transaction_id,
        tuition_id=tuition.id,
        amount=body.amount,
        channel="agent" if user.role == ROLE_STUDENT else "bank",
        created_by=user.user_id,
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError as exc:
        # Another request with the same transactionId won the race.
        db.rollback()
        if "uq_payments_transaction_id" in str(exc.orig):
            winner = db.scalar(select(Payment).where(Payment.transaction_id == body.transaction_id))
            raise _duplicate(db, user, winner) from exc
        raise

    total_paid = _paid_total(db, tuition.id)
    return PaymentResponse(
        status="SUCCESS",
        transaction_id=payment.transaction_id,
        student_no=tuition.student_no,
        term=tuition.term,
        paid_amount=payment.amount,
        total_paid=total_paid,
        remaining_balance=tuition.amount - total_paid,
        currency=tuition.currency,
    )
