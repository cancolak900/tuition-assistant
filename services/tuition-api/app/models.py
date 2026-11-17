"""ORM models (see docs/02_Technical_Design.md §4).

Balance is never stored: balance = tuitions.amount - SUM(payments.amount).
Business rules that the database can guarantee are also enforced as constraints.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

MONEY = Numeric(12, 2)
TERM_PATTERN = r"^[0-9]{4}-(FALL|SPRING)$"
ROLES = ("student", "bank", "admin")
CHANNELS = ("bank", "agent")


class Student(Base):
    __tablename__ = "students"

    student_no: Mapped[str] = mapped_column(String(16), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255))

    tuitions: Mapped[list["Tuition"]] = relationship(back_populates="student")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES}", name="role_valid"),
        # A student login must point at a student record; other roles must not.
        CheckConstraint("(role = 'student') = (student_no IS NOT NULL)", name="student_no_matches_role"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(16))
    student_no: Mapped[str | None] = mapped_column(ForeignKey("students.student_no", ondelete="RESTRICT"))


class Tuition(Base):
    __tablename__ = "tuitions"
    __table_args__ = (
        UniqueConstraint("student_no", "term", name="uq_tuitions_student_term"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(f"term ~ '{TERM_PATTERN}'", name="term_format"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_iso4217"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    student_no: Mapped[str] = mapped_column(ForeignKey("students.student_no", ondelete="RESTRICT"), index=True)
    term: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3), server_default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    student: Mapped[Student] = relationship(back_populates="tuitions")
    payments: Mapped[list["Payment"]] = relationship(back_populates="tuition")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(f"channel IN {CHANNELS}", name="channel_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    # Idempotency key: a retried payment with the same id is rejected by the database.
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True)
    tuition_id: Mapped[int] = mapped_column(ForeignKey("tuitions.id", ondelete="RESTRICT"), index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    channel: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tuition: Mapped[Tuition] = relationship(back_populates="payments")
