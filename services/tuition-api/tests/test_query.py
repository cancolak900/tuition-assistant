"""Query Tuition: mobile (no auth) and banking (JWT) endpoints (FR-01, FR-03, FR-12, FR-13)."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

MOBILE = "/api/v1/mobile/tuition"
BANKING = "/api/v1/banking/tuition"


# ---------- mobile ----------

def test_mobile_query_with_term(api):
    """T-03: existing student, term given -> 200 with correct total and balance."""
    res = api.get(f"{MOBILE}/S1001", params={"term": "2026-FALL"})
    assert res.status_code == 200
    assert res.json() == {
        "studentNo": "S1001",
        "term": "2026-FALL",
        "tuitionTotal": "3000.00",
        "totalPaid": "0.00",
        "balance": "3000.00",
        "currency": "USD",
        "terms": [{"term": "2026-FALL", "tuitionTotal": "3000.00", "totalPaid": "0.00", "balance": "3000.00"}],
    }


def test_mobile_query_overall_with_breakdown(api):
    """T-04: no term -> overall totals plus a chronological per-term breakdown that sums correctly."""
    body = api.get(f"{MOBILE}/S1001").json()
    assert body["term"] is None
    assert [t["term"] for t in body["terms"]] == ["2026-FALL", "2027-SPRING"]
    assert (body["tuitionTotal"], body["totalPaid"], body["balance"]) == ("6000.00", "0.00", "6000.00")
    assert sum(Decimal(t["balance"]) for t in body["terms"]) == Decimal(body["balance"])


def test_mobile_query_fully_paid_student(api):
    body = api.get(f"{MOBILE}/S1002", params={"term": "2026-FALL"}).json()
    assert (body["tuitionTotal"], body["totalPaid"], body["balance"]) == ("2500.00", "2500.00", "0.00")


def test_mobile_query_unknown_student_404(api):
    """T-05: unknown student -> 404."""
    res = api.get(f"{MOBILE}/S9999")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "STUDENT_NOT_FOUND"


def test_mobile_query_term_without_tuition_404(api):
    res = api.get(f"{MOBILE}/S1003", params={"term": "2027-SPRING"})
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "TUITION_NOT_FOUND"


@pytest.mark.parametrize("term", ["2026-WINTER", "2026-fall", "26-FALL"])
def test_mobile_query_malformed_term_422(api, term):
    """T-06: malformed term -> 422."""
    res = api.get(f"{MOBILE}/S1001", params={"term": term})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_mobile_query_needs_no_token(api):
    assert api.get(f"{MOBILE}/S1003").status_code == 200


# ---------- banking ----------

def test_banking_student_own_record(api, login):
    """T-07: student token, own number -> 200."""
    res = api.get(f"{BANKING}/S1001", params={"term": "2026-FALL"}, headers=login("s1001", "Pass1001!"))
    assert res.status_code == 200
    assert res.json()["balance"] == "3000.00"


def test_banking_student_other_student_403(api, login):
    """T-08: student token, other student -> 403 and no data leaked."""
    res = api.get(f"{BANKING}/S1002", headers=login("s1001", "Pass1001!"))
    assert res.status_code == 403
    body = res.json()
    assert body["error"]["code"] == "FORBIDDEN_OTHER_STUDENT"
    assert "balance" not in res.text


def test_banking_without_token_401(api):
    """T-09: no token -> 401."""
    res = api.get(f"{BANKING}/S1001")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_banking_bank_any_student(api, login):
    """T-10: bank token, any student -> 200."""
    headers = login("bank", "Bank123!")
    for student_no in ("S1001", "S1002", "S1003", "S1020"):
        assert api.get(f"{BANKING}/{student_no}", headers=headers).status_code == 200


def test_banking_admin_token_403(api, login):
    """FR-13: admin is not a banking client."""
    res = api.get(f"{BANKING}/S1001", headers=login("admin", "Admin123!"))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_banking_unknown_student_404_for_bank(api, login):
    res = api.get(f"{BANKING}/S9999", headers=login("bank", "Bank123!"))
    assert res.status_code == 404


# ---------- business rule ----------

def test_balance_uses_exact_decimals(api, seeded_url):
    """T-30: balance = amount - sum(payments) with Decimal: 1.00 - (0.10 + 0.20) == 0.70 exactly."""
    engine = create_engine(seeded_url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO students (student_no, full_name) VALUES ('T3000', 'Decimal Test') ON CONFLICT DO NOTHING"))
        tid = c.execute(text(
            "INSERT INTO tuitions (student_no, term, amount) VALUES ('T3000', '2030-FALL', 1.00) "
            "ON CONFLICT (student_no, term) DO UPDATE SET amount = EXCLUDED.amount RETURNING id"
        )).scalar_one()
        uid = c.execute(text("SELECT id FROM users WHERE username = 'bank'")).scalar_one()
        for tx, amount in (("T30-A", "0.10"), ("T30-B", "0.20")):
            c.execute(text(
                "INSERT INTO payments (transaction_id, tuition_id, amount, channel, created_by) "
                "VALUES (:tx, :t, :a, 'bank', :u) ON CONFLICT DO NOTHING"
            ), {"tx": tx, "t": tid, "a": amount, "u": uid})
    engine.dispose()

    body = api.get(f"{MOBILE}/T3000", params={"term": "2030-FALL"}).json()
    assert (body["tuitionTotal"], body["totalPaid"], body["balance"]) == ("1.00", "0.30", "0.70")


def test_overall_query_never_adds_different_currencies(api, login, seeded_url):
    """Mixed currencies: the overall total is refused (409), per-term queries still work."""
    engine = create_engine(seeded_url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO students (student_no, full_name) VALUES ('T3400', 'Currency Test') ON CONFLICT DO NOTHING"))
        c.execute(text("INSERT INTO tuitions (student_no, term, amount, currency) VALUES ('T3400', '2034-FALL', 100, 'USD'), ('T3400', '2035-SPRING', 100, 'EUR') ON CONFLICT DO NOTHING"))
    engine.dispose()
    res = api.get(f"{MOBILE}/T3400")
    assert (res.status_code, res.json()["error"]["code"]) == (409, "MIXED_CURRENCIES")
    assert api.get(f"{MOBILE}/T3400", params={"term": "2035-SPRING"}).json()["currency"] == "EUR"
