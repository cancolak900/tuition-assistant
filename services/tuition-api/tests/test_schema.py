"""Database schema and migrations (NFR-06, NFR-08, NFR-09).

Runs Alembic against a real PostgreSQL 16 container and checks that the database itself rejects
invalid data: duplicate (student, term), duplicate transaction id, non-positive amounts, bad terms.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app import models  # noqa: F401
from app.db import Base
from tests.conftest import alembic_config


@pytest.fixture
def engine(migrated_url):
    eng = create_engine(migrated_url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """A connection inside a transaction that is always rolled back, so tests never leak data."""
    with engine.connect() as c:
        tx = c.begin()
        yield c
        tx.rollback()


def _student(conn, no: str | None = None) -> str:
    no = no or "T" + uuid.uuid4().hex[:8].upper()
    conn.execute(text("INSERT INTO students (student_no, full_name) VALUES (:n, 'Test Student')"), {"n": no})
    return no


def _tuition(conn, student_no: str, term: str = "2026-FALL", amount: str = "3000.00") -> int:
    return conn.execute(
        text("INSERT INTO tuitions (student_no, term, amount) VALUES (:s, :t, :a) RETURNING id"),
        {"s": student_no, "t": term, "a": amount},
    ).scalar_one()


def _bank_user(conn) -> int:
    return conn.execute(
        text("INSERT INTO users (username, password_hash, role) VALUES (:u, 'x', 'bank') RETURNING id"),
        {"u": "bank-" + uuid.uuid4().hex[:8]},
    ).scalar_one()


def _expect_violation(conn, sql: str, params: dict, constraint: str) -> None:
    sp = conn.begin_nested()
    with pytest.raises(IntegrityError) as exc:
        conn.execute(text(sql), params)
    sp.rollback()
    assert constraint in str(exc.value)


def test_upgrade_head_creates_all_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert {"students", "users", "tuitions", "payments", "alembic_version"} <= tables


def test_models_match_migrations(engine):
    """Autogenerate finds no difference between the ORM models and the migrated schema."""
    with engine.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
    assert diff == []


def test_money_is_numeric_12_2(engine):
    cols = {c["name"]: c for c in inspect(engine).get_columns("tuitions")}
    assert (cols["amount"]["type"].precision, cols["amount"]["type"].scale) == (12, 2)


def test_currency_defaults_to_usd(conn):
    tid = _tuition(conn, _student(conn))
    assert conn.execute(text("SELECT currency FROM tuitions WHERE id = :i"), {"i": tid}).scalar_one() == "USD"


def test_duplicate_student_term_rejected(conn):
    """FR-07: one tuition record per (student, term); the API updates instead of inserting twice."""
    s = _student(conn)
    _tuition(conn, s)
    _expect_violation(conn, "INSERT INTO tuitions (student_no, term, amount) VALUES (:s, '2026-FALL', 1)", {"s": s}, "uq_tuitions_student_term")


def test_duplicate_transaction_id_rejected(conn):
    """FR-05 / NFR-08: the same transaction id can never be stored twice."""
    tid, uid = _tuition(conn, _student(conn)), _bank_user(conn)
    sql = "INSERT INTO payments (transaction_id, tuition_id, amount, channel, created_by) VALUES ('TX-1', :t, 10, 'bank', :u)"
    conn.execute(text(sql), {"t": tid, "u": uid})
    _expect_violation(conn, sql, {"t": tid, "u": uid}, "uq_payments_transaction_id")


@pytest.mark.parametrize("amount", ["0", "-5.00"])
def test_non_positive_amounts_rejected(conn, amount):
    s = _student(conn)
    _expect_violation(conn, "INSERT INTO tuitions (student_no, term, amount) VALUES (:s, '2026-FALL', :a)", {"s": s, "a": amount}, "ck_tuitions_amount_positive")
    tid, uid = _tuition(conn, s), _bank_user(conn)
    _expect_violation(
        conn,
        "INSERT INTO payments (transaction_id, tuition_id, amount, channel, created_by) VALUES ('TX-NEG', :t, :a, 'bank', :u)",
        {"t": tid, "a": amount, "u": uid},
        "ck_payments_amount_positive",
    )


@pytest.mark.parametrize("term", ["2026-WINTER", "26-FALL", "2026-fall"])
def test_bad_term_format_rejected(conn, term):
    s = _student(conn)
    _expect_violation(conn, "INSERT INTO tuitions (student_no, term, amount) VALUES (:s, :t, 1)", {"s": s, "t": term}, "ck_tuitions_term_format")


def test_student_login_requires_student_no(conn):
    _expect_violation(conn, "INSERT INTO users (username, password_hash, role) VALUES ('s-x', 'x', 'student')", {}, "ck_users_student_no_matches_role")


def test_unknown_role_rejected(conn):
    _expect_violation(conn, "INSERT INTO users (username, password_hash, role) VALUES ('r-x', 'x', 'root')", {}, "ck_users_role_valid")


def test_amounts_round_trip_as_exact_decimals(conn):
    tid = _tuition(conn, _student(conn), amount="1234.56")
    assert conn.execute(text("SELECT amount FROM tuitions WHERE id = :i"), {"i": tid}).scalar_one() == Decimal("1234.56")


def test_downgrade_and_upgrade_round_trip(postgres_url):
    """Runs on its own scratch database so the shared (seeded) test database is never dropped."""
    from sqlalchemy.engine import make_url

    admin = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS migration_roundtrip"))
        c.execute(text("CREATE DATABASE migration_roundtrip"))
    scratch_url = make_url(postgres_url).set(database="migration_roundtrip").render_as_string(hide_password=False)
    scratch = create_engine(scratch_url)
    try:
        cfg = alembic_config(scratch_url)
        command.upgrade(cfg, "head")
        assert {"students", "users", "tuitions", "payments"} <= set(inspect(scratch).get_table_names())
        command.downgrade(cfg, "base")
        assert set(inspect(scratch).get_table_names()) <= {"alembic_version"}
        command.upgrade(cfg, "head")
        assert {"students", "users", "tuitions", "payments"} <= set(inspect(scratch).get_table_names())
    finally:
        scratch.dispose()
        with admin.connect() as c:
            c.execute(text("DROP DATABASE IF EXISTS migration_roundtrip"))
        admin.dispose()
