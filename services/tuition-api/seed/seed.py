"""Load demo data. Safe to run more than once (existing rows are left untouched).

Usage (inside the container):  python -m seed.seed

Demo logins (also listed in the README):
    s1001 / Pass1001!   student S1001   2026-FALL $3,000 unpaid, 2027-SPRING $3,000
    s1002 / Pass1002!   student S1002   2026-FALL $2,500 fully paid (balance 0)
    s1003 / Pass1003!   student S1003   2026-FALL $250 (below the $300 installment threshold)
    bank  / Bank123!    bank
    admin / Admin123!   admin
Plus 27 students without logins (S1004-S1030) so the unpaid list spans several pages.
"""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.models import Payment, Student, Tuition, User
from app.security import hash_password

logger = logging.getLogger("seed")

FALL, SPRING = "2026-FALL", "2027-SPRING"

DEMO_STUDENTS = [
    ("S1001", "Ayse Yilmaz", "s1001@uni.example.edu"),
    ("S1002", "Mehmet Demir", "s1002@uni.example.edu"),
    ("S1003", "Elif Kaya", "s1003@uni.example.edu"),
]

USERS = [
    ("s1001", "Pass1001!", "student", "S1001"),
    ("s1002", "Pass1002!", "student", "S1002"),
    ("s1003", "Pass1003!", "student", "S1003"),
    ("bank", "Bank123!", "bank", None),
    ("admin", "Admin123!", "admin", None),
]

DEMO_TUITIONS = [
    ("S1001", FALL, "3000.00"),
    ("S1001", SPRING, "3000.00"),
    ("S1002", FALL, "2500.00"),
    ("S1003", FALL, "250.00"),
]

FIRST = ["Zeynep", "Emre", "Mert", "Selin", "Burak", "Deniz", "Kerem", "Ece", "Onur", "Derya", "Kaan", "Irem", "Baris", "Seda"]
LAST = ["Arslan", "Celik", "Sahin", "Ozturk", "Aydin", "Koc", "Polat", "Kurt", "Dogan", "Yildiz", "Aksoy", "Tekin", "Bulut"]


def extra_students() -> list[tuple[str, str, str, Decimal, Decimal]]:
    """27 deterministic students: (no, name, email, fall tuition, already paid). Every 5th one is fully paid."""
    rows = []
    for i in range(27):
        no = f"S{1004 + i}"
        name = f"{FIRST[i % len(FIRST)]} {LAST[(i * 5) % len(LAST)]}"
        amount = Decimal(2500 + (i % 4) * 500)  # 2500, 3000, 3500, 4000
        if i % 5 == 4:
            paid = amount
        elif i % 3 == 1:
            paid = Decimal(1000)
        else:
            paid = Decimal(0)
        rows.append((no, name, f"{no.lower()}@uni.example.edu", amount, paid))
    return rows


def _insert_ignore(session: Session, model, rows: list[dict], conflict: list[str]) -> None:
    if rows:
        session.execute(insert(model).values(rows).on_conflict_do_nothing(index_elements=conflict))


def seed(session: Session) -> dict[str, int]:
    extras = extra_students()

    students = [{"student_no": n, "full_name": f, "email": e} for n, f, e in DEMO_STUDENTS]
    students += [{"student_no": n, "full_name": f, "email": e} for n, f, e, _, _ in extras]
    _insert_ignore(session, Student, students, ["student_no"])

    existing_users = set(session.scalars(select(User.username)))
    users = [
        {"username": u, "password_hash": hash_password(p), "role": r, "student_no": s}
        for u, p, r, s in USERS
        if u not in existing_users  # avoid hashing (slow) for rows that already exist
    ]
    _insert_ignore(session, User, users, ["username"])

    tuitions = [{"student_no": s, "term": t, "amount": Decimal(a), "currency": "USD"} for s, t, a in DEMO_TUITIONS]
    tuitions += [{"student_no": n, "term": FALL, "amount": a, "currency": "USD"} for n, _, _, a, _ in extras]
    _insert_ignore(session, Tuition, tuitions, ["student_no", "term"])

    bank_id = session.scalar(select(User.id).where(User.username == "bank"))
    tuition_ids = {(s, t): i for i, s, t in session.execute(select(Tuition.id, Tuition.student_no, Tuition.term))}
    payments = [("S1002", FALL, Decimal("2500.00"))] + [(n, FALL, p) for n, _, _, _, p in extras if p > 0]
    _insert_ignore(
        session,
        Payment,
        [
            {"transaction_id": f"SEED-{s}-{t}", "tuition_id": tuition_ids[(s, t)], "amount": amt, "channel": "bank", "created_by": bank_id}
            for s, t, amt in payments
        ],
        ["transaction_id"],
    )

    session.commit()
    return {
        "students": len(students),
        "users": len(USERS),
        "tuitions": len(tuitions),
        "payments": len(payments),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    with get_sessionmaker()() as session:
        counts = seed(session)
    logger.info("Seed complete (rows ensured): %s", counts)


if __name__ == "__main__":
    main()
