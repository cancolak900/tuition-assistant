"""Pay Tuition (FR-04..FR-06, FR-12, NFR-08).

Every test creates its own student (with a student login) and tuition, so payments never change
the shared seed data used by other tests.
"""

import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from app.security import hash_password

PAY = "/api/v1/banking/payments"
TERM = "2031-FALL"  # a term no other test uses
_HASH = hash_password("Student123!")


@pytest.fixture
def new_student(seeded_url, api):
    """new_student("1000.00") -> (student_no, student_auth_headers)."""
    engine = create_engine(seeded_url)

    def _make(amount: str = "1000.00"):
        no = "P" + uuid.uuid4().hex[:8].upper()
        with engine.begin() as c:
            c.execute(text("INSERT INTO students (student_no, full_name) VALUES (:n, 'Payment Test')"), {"n": no})
            c.execute(text("INSERT INTO tuitions (student_no, term, amount) VALUES (:n, :t, :a)"), {"n": no, "t": TERM, "a": amount})
            c.execute(text("INSERT INTO users (username, password_hash, role, student_no) VALUES (:u, :h, 'student', :n)"), {"u": no.lower(), "h": _HASH, "n": no})
        token = api.post("/api/v1/auth/login", json={"username": no.lower(), "password": "Student123!"}).json()["accessToken"]
        return no, {"Authorization": f"Bearer {token}"}

    yield _make
    engine.dispose()


def _body(student_no: str, amount: str, tx: str | None = None, term: str = TERM) -> dict:
    return {"studentNo": student_no, "term": term, "amount": amount, "transactionId": tx or "TX-" + uuid.uuid4().hex}


def _balance(api, student_no: str) -> str:
    return api.get(f"/api/v1/mobile/tuition/{student_no}", params={"term": TERM}).json()["balance"]


def test_partial_payment(api, new_student):
    """T-11: partial payment -> 201 and remaining = balance - amount."""
    no, headers = new_student("1000.00")
    res = api.post(PAY, json=_body(no, "250.50"), headers=headers)
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "SUCCESS"
    assert (body["paidAmount"], body["totalPaid"], body["remainingBalance"], body["currency"]) == ("250.50", "250.50", "749.50", "USD")
    assert _balance(api, no) == "749.50"


def test_full_payment(api, new_student):
    """T-12: full payment -> 201 and remaining = 0.00."""
    no, headers = new_student("1000.00")
    api.post(PAY, json=_body(no, "400.00"), headers=headers)
    res = api.post(PAY, json=_body(no, "600.00"), headers=headers)
    assert res.status_code == 201
    assert (res.json()["totalPaid"], res.json()["remainingBalance"]) == ("1000.00", "0.00")


def test_duplicate_transaction_id_409(api, new_student):
    """T-13: same transactionId twice -> 409 and the balance is unchanged."""
    no, headers = new_student("1000.00")
    body = _body(no, "100.00", tx="TX-DUP-" + no)
    assert api.post(PAY, json=body, headers=headers).status_code == 201
    again = api.post(PAY, json=body, headers=headers)
    assert again.status_code == 409
    err = again.json()["error"]
    assert err["code"] == "DUPLICATE_TRANSACTION"
    assert err["details"]["transactionId"] == body["transactionId"]
    assert err["details"]["paidAmount"] == "100.00"
    assert _balance(api, no) == "900.00"


def test_amount_greater_than_balance_422(api, new_student):
    """T-14: amount > balance -> 422 AMOUNT_EXCEEDS_BALANCE, nothing recorded."""
    no, headers = new_student("1000.00")
    res = api.post(PAY, json=_body(no, "1000.01"), headers=headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "AMOUNT_EXCEEDS_BALANCE"
    assert res.json()["error"]["details"]["balance"] == "1000.00"
    assert _balance(api, no) == "1000.00"


def test_payment_on_zero_balance_422(api, new_student):
    no, headers = new_student("50.00")
    api.post(PAY, json=_body(no, "50.00"), headers=headers)
    res = api.post(PAY, json=_body(no, "0.01"), headers=headers)
    assert res.status_code == 422


@pytest.mark.parametrize("amount", ["0", "0.00", "-10.00", "10.001", "abc"])
def test_invalid_amount_422(api, new_student, amount):
    """T-15: amount <= 0 or more than 2 decimals -> 422."""
    no, headers = new_student("1000.00")
    res = api.post(PAY, json=_body(no, amount), headers=headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert _balance(api, no) == "1000.00"


def test_student_pays_for_other_student_403(api, new_student):
    """T-16: student pays for another student -> 403 and nothing recorded."""
    me, my_headers = new_student("1000.00")
    other, _ = new_student("1000.00")
    res = api.post(PAY, json=_body(other, "10.00"), headers=my_headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN_OTHER_STUDENT"
    assert _balance(api, other) == "1000.00"


def test_unknown_term_404(api, new_student):
    """T-17: term without a tuition for this student -> 404."""
    no, headers = new_student("1000.00")
    res = api.post(PAY, json=_body(no, "10.00", term="2032-SPRING"), headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "TUITION_NOT_FOUND"


def test_bank_can_pay_for_any_student(api, login, new_student):
    no, _ = new_student("1000.00")
    res = api.post(PAY, json=_body(no, "10.00"), headers=login("bank", "Bank123!"))
    assert res.status_code == 201


def test_payment_requires_token_and_banking_role(api, login, new_student):
    no, _ = new_student("1000.00")
    assert api.post(PAY, json=_body(no, "10.00")).status_code == 401
    res = api.post(PAY, json=_body(no, "10.00"), headers=login("admin", "Admin123!"))
    assert res.status_code == 403


def test_channel_records_who_paid(api, login, new_student, seeded_url):
    no, student_headers = new_student("1000.00")
    api.post(PAY, json=_body(no, "1.00", tx="TX-CH-S-" + no), headers=student_headers)
    api.post(PAY, json=_body(no, "1.00", tx="TX-CH-B-" + no), headers=login("bank", "Bank123!"))
    engine = create_engine(seeded_url)
    with engine.connect() as c:
        channels = dict(c.execute(text("SELECT transaction_id, channel FROM payments WHERE transaction_id LIKE :p"), {"p": f"TX-CH-%-{no}"}).all())
    engine.dispose()
    assert channels == {f"TX-CH-S-{no}": "agent", f"TX-CH-B-{no}": "bank"}


def test_concurrent_payments_cannot_overdraw(api, make_client, seeded_url, new_student):
    """Row lock: two simultaneous 600.00 payments on a 1000.00 balance -> exactly one succeeds."""
    no, headers = new_student("1000.00")
    clients = [make_client(seeded_url) for _ in range(2)]
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def pay(client):
        barrier.wait()
        codes.append(client.post(PAY, json=_body(no, "600.00"), headers=headers).status_code)

    threads = [threading.Thread(target=pay, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [201, 422]
    assert Decimal(_balance(api, no)) == Decimal("400.00")


def test_concurrent_same_transaction_id_applied_once(api, make_client, seeded_url, new_student):
    """Idempotency under a race: the same transactionId sent twice at once is applied once."""
    no, headers = new_student("1000.00")
    body = _body(no, "100.00", tx="TX-RACE-" + no)
    clients = [make_client(seeded_url) for _ in range(2)]
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def pay(client):
        barrier.wait()
        codes.append(client.post(PAY, json=body, headers=headers).status_code)

    threads = [threading.Thread(target=pay, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [201, 409]
    assert _balance(api, no) == "900.00"
