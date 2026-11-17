"""Admin API: Add Tuition, Batch upload, Unpaid list (FR-07..FR-09, FR-13).

Tests that change data use their own students/terms, or restore what they changed,
so the shared seed data stays as documented.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

ADD = "/api/v1/admin/tuition"
BATCH = "/api/v1/admin/tuition/batch"
UNPAID = "/api/v1/admin/tuition/unpaid"
TERM = "2033-FALL"
SAMPLE = Path(__file__).resolve().parents[1] / "seed" / "sample_batch.csv"
SEED_UNPAID_2026_FALL = 24  # 22 extra students + S1001 + S1003 (S1002 and every 5th extra are fully paid)


@pytest.fixture
def admin(login):
    return login("admin", "Admin123!")


@pytest.fixture
def db(seeded_url):
    engine = create_engine(seeded_url)
    yield engine
    engine.dispose()


@pytest.fixture
def new_student(db):
    def _make() -> str:
        no = "A" + uuid.uuid4().hex[:8].upper()
        with db.begin() as c:
            c.execute(text("INSERT INTO students (student_no, full_name) VALUES (:n, 'Admin Test')"), {"n": no})
        return no

    return _make


def _csv(rows: list[str], header: str = "studentNo,term,amount,currency") -> dict:
    return {"file": ("batch.csv", ("\n".join([header, *rows]) + "\n").encode(), "text/csv")}


# ---------- Add Tuition ----------

def test_add_tuition_new_record_201(api, admin, new_student):
    """T-18: new record -> 201 CREATED."""
    no = new_student()
    res = api.post(ADD, json={"studentNo": no, "term": TERM, "amount": "4200.00", "currency": "USD"}, headers=admin)
    assert res.status_code == 201
    assert res.json() == {"status": "CREATED", "studentNo": no, "term": TERM, "amount": "4200.00", "currency": "USD"}
    assert api.get(f"/api/v1/mobile/tuition/{no}", params={"term": TERM}).json()["balance"] == "4200.00"


def test_add_tuition_same_student_term_updates_200(api, admin, new_student):
    """T-19: same student+term again -> 200 UPDATED with the new amount."""
    no = new_student()
    api.post(ADD, json={"studentNo": no, "term": TERM, "amount": "4200.00"}, headers=admin)
    res = api.post(ADD, json={"studentNo": no, "term": TERM, "amount": "4500.00"}, headers=admin)
    assert res.status_code == 200
    assert (res.json()["status"], res.json()["amount"], res.json()["previousAmount"]) == ("UPDATED", "4500.00", "4200.00")
    summary = api.get(f"/api/v1/mobile/tuition/{no}").json()
    assert len(summary["terms"]) == 1 and summary["tuitionTotal"] == "4500.00"


def test_add_tuition_below_paid_409(api, admin, login, new_student):
    """T-20: update below the amount already paid -> 409, record unchanged."""
    no = new_student()
    api.post(ADD, json={"studentNo": no, "term": TERM, "amount": "1000.00"}, headers=admin)
    pay = {"studentNo": no, "term": TERM, "amount": "600.00", "transactionId": "TX-ADM-" + no}
    assert api.post("/api/v1/banking/payments", json=pay, headers=login("bank", "Bank123!")).status_code == 201
    res = api.post(ADD, json={"studentNo": no, "term": TERM, "amount": "500.00"}, headers=admin)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "AMOUNT_BELOW_PAID"
    assert api.get(f"/api/v1/mobile/tuition/{no}", params={"term": TERM}).json()["tuitionTotal"] == "1000.00"
    # changing the currency after a payment is refused too
    res = api.post(ADD, json={"studentNo": no, "term": TERM, "amount": "1000.00", "currency": "EUR"}, headers=admin)
    assert (res.status_code, res.json()["error"]["code"]) == (409, "CURRENCY_CHANGE_NOT_ALLOWED")


@pytest.mark.parametrize(("username", "password"), [("s1001", "Pass1001!"), ("bank", "Bank123!")])
def test_add_tuition_non_admin_403(api, login, username, password):
    """T-21: non-admin token -> 403."""
    res = api.post(ADD, json={"studentNo": "S1001", "term": TERM, "amount": "1.00"}, headers=login(username, password))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_add_tuition_without_token_401(api):
    assert api.post(ADD, json={"studentNo": "S1001", "term": TERM, "amount": "1.00"}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"amount": "100.00", "currency": "usd"},
        {"amount": "100.00", "currency": "DOLLAR"},
        {"amount": "-1.00", "currency": "USD"},
        {"amount": "0", "currency": "USD"},
        {"amount": "1.234", "currency": "USD"},
    ],
)
def test_add_tuition_invalid_input_422(api, admin, body):
    """T-22: invalid currency / non-positive or over-precise amount -> 422."""
    res = api.post(ADD, json={"studentNo": "S1001", "term": TERM, **body}, headers=admin)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_add_tuition_unknown_student_404(api, admin):
    res = api.post(ADD, json={"studentNo": "S9999", "term": TERM, "amount": "1.00"}, headers=admin)
    assert (res.status_code, res.json()["error"]["code"]) == (404, "STUDENT_NOT_FOUND")


# ---------- Batch ----------

def test_batch_all_rows_valid(api, admin, new_student):
    """T-23: all rows valid -> successCount = n, failureCount = 0."""
    a, b, c = new_student(), new_student(), new_student()
    res = api.post(BATCH, files=_csv([f"{a},{TERM},1000.00,USD", f"{b},{TERM},2000.00,USD", f"{c},{TERM},3000.50,EUR"]), headers=admin)
    assert res.status_code == 200
    body = res.json()
    assert (body["status"], body["totalRows"], body["successCount"], body["failureCount"], body["createdCount"]) == ("COMPLETED", 3, 3, 0, 3)
    assert body["errors"] == []
    assert api.get(f"/api/v1/mobile/tuition/{c}").json()["currency"] == "EUR"


def test_batch_mixed_rows_partial_success(api, admin, new_student):
    """T-24: mixed rows -> good rows are kept, errors list the line numbers."""
    a, b = new_student(), new_student()
    rows = [
        f"{a},{TERM},1000.00,USD",  # line 2 ok
        f"{b},2033-WINTER,1000.00,USD",  # line 3 bad term
        f"S9999,{TERM},1000.00,USD",  # line 4 unknown student
        f"{b},{TERM},-5,USD",  # line 5 negative
        f"{b},{TERM},1500.00,USD",  # line 6 ok
        f"{a},{TERM},1100.00,USD",  # line 7 ok (update of line 2)
    ]
    body = api.post(BATCH, files=_csv(rows), headers=admin).json()
    assert (body["status"], body["successCount"], body["failureCount"], body["createdCount"], body["updatedCount"]) == ("PARTIAL", 3, 3, 2, 1)
    assert [(e["row"], e["code"]) for e in body["errors"]] == [(3, "INVALID_TERM"), (4, "STUDENT_NOT_FOUND"), (5, "INVALID_AMOUNT")]
    assert api.get(f"/api/v1/mobile/tuition/{a}").json()["tuitionTotal"] == "1100.00"
    assert api.get(f"/api/v1/mobile/tuition/{b}").json()["tuitionTotal"] == "1500.00"


def test_batch_sample_file(api, admin, db):
    """The committed demo file: 6 valid rows, 7 rows with one error each. Changes are undone afterwards."""
    with db.connect() as c:
        original_s1014 = c.execute(text("SELECT amount FROM tuitions WHERE student_no='S1014' AND term='2026-FALL'")).scalar_one()
    try:
        body = api.post(BATCH, files={"file": ("sample_batch.csv", SAMPLE.read_bytes(), "text/csv")}, headers=admin).json()
        assert (body["status"], body["totalRows"], body["successCount"], body["failureCount"]) == ("PARTIAL", 13, 6, 7)
        assert (body["createdCount"], body["updatedCount"]) == (5, 1)
        assert sorted(e["code"] for e in body["errors"]) == sorted([
            "INVALID_TERM", "INVALID_AMOUNT", "STUDENT_NOT_FOUND", "INVALID_AMOUNT", "INVALID_CURRENCY", "AMOUNT_BELOW_PAID", "INVALID_AMOUNT",
        ])
    finally:
        with db.begin() as c:
            c.execute(text("DELETE FROM tuitions WHERE term='2027-SPRING' AND student_no IN ('S1004','S1005','S1006','S1007','S1013')"))
            c.execute(text("UPDATE tuitions SET amount=:a WHERE student_no='S1014' AND term='2026-FALL'"), {"a": original_s1014})


@pytest.mark.parametrize(
    "files",
    [
        _csv(["S1001,2033-FALL,1.00,USD"], header="student,term,amount,currency"),  # wrong header
        {"file": ("batch.csv", b"", "text/csv")},  # empty
        {"file": ("photo.png", b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image/png")},  # binary
        {"file": ("batch.csv", "studentNo,term,amount,currency\n".encode("utf-16"), "text/csv")},  # not UTF-8
    ],
    ids=["wrong-header", "empty", "binary", "utf16"],
)
def test_batch_bad_file_400(api, admin, files):
    """T-25: wrong header / non-CSV file -> 400."""
    res = api.post(BATCH, files=files, headers=admin)
    assert res.status_code == 400
    assert res.json()["error"]["code"] in {"INVALID_CSV_HEADER", "INVALID_FILE"}


def test_batch_missing_file_422(api, admin):
    assert api.post(BATCH, headers=admin).status_code == 422


def test_batch_non_admin_403(api, login):
    assert api.post(BATCH, files=_csv([]), headers=login("bank", "Bank123!")).status_code == 403


# ---------- Unpaid list ----------

def test_unpaid_paging(api, admin):
    """T-26: page 1 and page 2 slice correctly and totalPages is right."""
    p1 = api.get(UNPAID, params={"term": "2026-FALL", "page": 1, "pageSize": 10}, headers=admin).json()
    p2 = api.get(UNPAID, params={"term": "2026-FALL", "page": 2, "pageSize": 10}, headers=admin).json()
    p3 = api.get(UNPAID, params={"term": "2026-FALL", "page": 3, "pageSize": 10}, headers=admin).json()
    assert (p1["totalItems"], p1["totalPages"], p1["page"], p1["pageSize"]) == (SEED_UNPAID_2026_FALL, 3, 1, 10)
    assert (len(p1["items"]), len(p2["items"]), len(p3["items"])) == (10, 10, 4)
    numbers = [i["studentNo"] for p in (p1, p2, p3) for i in p["items"]]
    assert numbers == sorted(numbers) and len(set(numbers)) == SEED_UNPAID_2026_FALL
    first = p1["items"][0]
    assert first == {"studentNo": "S1001", "fullName": "Ayse Yilmaz", "tuitionTotal": "3000.00", "paid": "0.00", "balance": "3000.00", "currency": "USD"}


def test_unpaid_excludes_fully_paid(api, admin):
    """T-27: fully paid students are not listed; partly paid ones show the remaining balance."""
    items = api.get(UNPAID, params={"term": "2026-FALL", "pageSize": 100}, headers=admin).json()["items"]
    numbers = {i["studentNo"] for i in items}
    assert "S1002" not in numbers  # paid in full
    assert {"S1008", "S1013", "S1018", "S1023", "S1028"}.isdisjoint(numbers)  # every 5th extra student is paid in full
    partly = next(i for i in items if i["studentNo"] == "S1005")
    assert (partly["paid"], partly["balance"]) == ("1000.00", "2000.00")


def test_unpaid_page_past_the_end_is_empty(api, admin):
    body = api.get(UNPAID, params={"term": "2026-FALL", "page": 99}, headers=admin).json()
    assert body["items"] == [] and body["totalItems"] == SEED_UNPAID_2026_FALL


@pytest.mark.parametrize("params", [{"pageSize": 0}, {"pageSize": 101}, {"page": 0}, {"term": "2026-WINTER"}, {"term": None}])
def test_unpaid_invalid_paging_422(api, admin, params):
    """T-28: pageSize 0 or 101 (and other bad paging input) -> 422."""
    query = {"term": "2026-FALL", **params}
    res = api.get(UNPAID, params={k: v for k, v in query.items() if v is not None}, headers=admin)
    assert res.status_code == 422


@pytest.mark.parametrize(("username", "password"), [("s1001", "Pass1001!"), ("bank", "Bank123!")])
def test_unpaid_non_admin_403(api, login, username, password):
    """T-29: non-admin -> 403."""
    assert api.get(UNPAID, params={"term": "2026-FALL"}, headers=login(username, password)).status_code == 403


def test_batch_skips_blank_lines_and_reports_wrong_column_count(api, admin, new_student):
    a = new_student()
    body = api.post(BATCH, files=_csv([f"{a},{TERM},10.00,USD", "", f"{a},{TERM},10.00", " , , , "]), headers=admin).json()
    assert (body["totalRows"], body["successCount"], body["failureCount"]) == (2, 1, 1)
    assert (body["errors"][0]["row"], body["errors"][0]["code"]) == (4, "INVALID_COLUMNS")


def test_batch_rejects_non_utf8_text(api, admin):
    files = {"file": ("batch.csv", "studentNo,term,amount,currency\nS1001,2033-FALL,1.00,USD\nÉ\n".encode("latin-1"), "text/csv")}
    res = api.post(BATCH, files=files, headers=admin)
    assert (res.status_code, res.json()["error"]["code"]) == (400, "INVALID_FILE")


def test_batch_size_and_row_limits(api, admin, monkeypatch):
    from app.services import admin as admin_service

    monkeypatch.setattr(admin_service, "MAX_CSV_BYTES", 40)
    res = api.post(BATCH, files=_csv(["S9999,2033-FALL,1.00,USD"]), headers=admin)
    assert (res.status_code, res.json()["error"]["code"]) == (400, "FILE_TOO_LARGE")

    monkeypatch.setattr(admin_service, "MAX_CSV_BYTES", 1_000_000)
    monkeypatch.setattr(admin_service, "MAX_CSV_ROWS", 2)
    res = api.post(BATCH, files=_csv(["S9999,2033-FALL,1.00,USD"] * 3), headers=admin)
    assert (res.status_code, res.json()["error"]["code"]) == (400, "TOO_MANY_ROWS")
