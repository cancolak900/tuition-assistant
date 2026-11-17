"""Seed data and the sample batch CSV (demo users, paging data, deliberate bad rows)."""

import csv
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Payment, Student, Tuition, User
from app.security import verify_password
from seed.seed import USERS, seed

CSV_PATH = Path(__file__).resolve().parents[1] / "seed" / "sample_batch.csv"


@pytest.fixture
def session(seeded_url):
    engine = create_engine(seeded_url)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _balance(session: Session, student_no: str, term: str) -> Decimal:
    tuition = session.scalar(select(Tuition).where(Tuition.student_no == student_no, Tuition.term == term))
    paid = session.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.tuition_id == tuition.id))
    return tuition.amount - paid


def test_demo_users_exist_with_bcrypt_passwords(session):
    for username, password, role, student_no in USERS:
        user = session.scalar(select(User).where(User.username == username))
        assert user is not None, username
        assert (user.role, user.student_no) == (role, student_no)
        assert user.password_hash.startswith("$2")  # bcrypt, never plain text
        assert verify_password(password, user.password_hash)
        assert not verify_password("wrong-password", user.password_hash)


def test_demo_balances_match_the_design(session):
    assert _balance(session, "S1001", "2026-FALL") == Decimal("3000.00")
    assert _balance(session, "S1001", "2027-SPRING") == Decimal("3000.00")
    assert _balance(session, "S1002", "2026-FALL") == Decimal("0.00")
    assert _balance(session, "S1003", "2026-FALL") == Decimal("250.00")


def test_enough_unpaid_students_for_several_pages(session):
    """FR-09 demo: the unpaid list for 2026-FALL must not fit on one page of 10."""
    paid = select(Payment.tuition_id, func.sum(Payment.amount).label("paid")).group_by(Payment.tuition_id).subquery()
    unpaid = session.scalar(
        select(func.count())
        .select_from(Tuition)
        .outerjoin(paid, paid.c.tuition_id == Tuition.id)
        .where(Tuition.term == "2026-FALL", Tuition.amount - func.coalesce(paid.c.paid, 0) > 0)
    )
    assert unpaid > 20
    assert session.scalar(select(func.count()).select_from(Student)) >= 28


def test_seed_is_idempotent(session):
    before = [session.scalar(select(func.count()).select_from(m)) for m in (Student, User, Tuition, Payment)]
    seed(session)
    after = [session.scalar(select(func.count()).select_from(m)) for m in (Student, User, Tuition, Payment)]
    assert before == after


def test_sample_batch_has_valid_and_invalid_rows():
    """FR-08 demo file: correct header, some valid rows and one row per kind of error."""
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == ["studentNo", "term", "amount", "currency"]
    bad_terms = [r for r in rows if r["term"].split("-")[-1] not in ("FALL", "SPRING")]
    bad_amounts = [r for r in rows if not r["amount"].replace(".", "", 1).isdigit()]
    assert len(rows) >= 10
    assert bad_terms and bad_amounts
    assert any(r["studentNo"] == "S9999" for r in rows)  # unknown student
    assert any(r["currency"] != r["currency"].upper() or len(r["currency"]) != 3 for r in rows)  # bad currency
