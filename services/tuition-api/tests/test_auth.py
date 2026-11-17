"""Login, JWT validation and authorization rules (FR-10..FR-13, NFR-07)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.config import get_settings
from app.errors import AppError
from app.security import ALGORITHM, CurrentUser, ensure_student_access

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


def _token(**overrides) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    claims = {"iss": s.jwt_issuer, "sub": "1", "username": "s1001", "role": "student", "studentNo": "S1001", "iat": now, "exp": now + timedelta(minutes=5)}
    claims.update(overrides)
    secret = claims.pop("_secret", s.jwt_secret)
    return jwt.encode({k: v for k, v in claims.items() if v is not ...}, secret, algorithm=ALGORITHM)


# ---------- login ----------

def test_login_valid_credentials_returns_jwt(api):
    """T-01: valid credentials -> 200 and a JWT carrying role and studentNo."""
    res = api.post(LOGIN, json={"username": "s1001", "password": "Pass1001!"})
    assert res.status_code == 200
    body = res.json()
    assert body["tokenType"] == "bearer"
    assert body["expiresIn"] == 3600
    assert (body["role"], body["studentNo"]) == ("student", "S1001")

    claims = jwt.decode(body["accessToken"], get_settings().jwt_secret, algorithms=[ALGORITHM], issuer="tuition-auth")
    assert (claims["role"], claims["studentNo"], claims["username"]) == ("student", "S1001", "s1001")
    assert claims["exp"] - claims["iat"] == 3600


@pytest.mark.parametrize(("username", "password", "role"), [("bank", "Bank123!", "bank"), ("admin", "Admin123!", "admin")])
def test_login_non_student_roles_have_no_student_no(api, username, password, role):
    body = api.post(LOGIN, json={"username": username, "password": password}).json()
    assert (body["role"], body["studentNo"]) == (role, None)


def test_login_wrong_password_401(api):
    """T-02: wrong password -> 401 INVALID_CREDENTIALS."""
    res = api.post(LOGIN, json={"username": "s1001", "password": "nope"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_user_looks_like_wrong_password(api):
    """Unknown usernames cannot be told apart from wrong passwords."""
    unknown = api.post(LOGIN, json={"username": "ghost", "password": "x"})
    wrong = api.post(LOGIN, json={"username": "s1001", "password": "x"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_login_missing_fields_422(api):
    res = api.post(LOGIN, json={"username": "s1001"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
    assert any(d["field"] == "password" for d in res.json()["error"]["details"])


# ---------- token validation ----------

def test_me_with_valid_token(api, login):
    res = api.get(ME, headers=login("s1001", "Pass1001!"))
    assert res.status_code == 200
    assert res.json() | {"userId": 0} == {"userId": 0, "username": "s1001", "role": "student", "studentNo": "S1001"}


def test_me_without_token_401(api):
    """T-09 (token part): no token -> 401."""
    res = api.get(ME)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


def test_expired_token_401(api):
    """T-09 (token part): expired token -> 401 TOKEN_EXPIRED."""
    past = datetime.now(UTC) - timedelta(hours=2)
    res = api.get(ME, headers={"Authorization": f"Bearer {_token(iat=past, exp=past + timedelta(minutes=60))}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"_secret": "another-secret-that-is-also-long-enough-to-sign"},  # forged signature
        {"iss": "someone-else"},  # wrong issuer
        {"exp": ...},  # no expiry
        {"role": "superuser"},  # unknown role
        {"studentNo": None},  # student token without studentNo
    ],
    ids=["bad-signature", "wrong-issuer", "no-exp", "unknown-role", "student-without-number"],
)
def test_invalid_tokens_401(api, overrides):
    res = api.get(ME, headers={"Authorization": f"Bearer {_token(**overrides)}"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_TOKEN"


def test_garbage_token_401(api):
    res = api.get(ME, headers={"Authorization": "Bearer not.a.jwt"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_TOKEN"


# ---------- authorization rule used by the banking endpoints ----------

STUDENT = CurrentUser(1, "s1001", "student", "S1001")
BANK = CurrentUser(4, "bank", "bank", None)
ADMIN = CurrentUser(5, "admin", "admin", None)


def test_student_can_access_own_records():
    """T-07 (rule): a student may access its own studentNo."""
    ensure_student_access(STUDENT, "S1001")


def test_student_cannot_access_other_student():
    """T-08 / T-16 (rule): a student acting for another student -> 403 FORBIDDEN_OTHER_STUDENT."""
    with pytest.raises(AppError) as exc:
        ensure_student_access(STUDENT, "S1002")
    assert (exc.value.status_code, exc.value.code) == (403, "FORBIDDEN_OTHER_STUDENT")


def test_bank_can_access_any_student():
    """T-10 (rule): bank may act for any student."""
    ensure_student_access(BANK, "S1002")


def test_admin_cannot_use_banking():
    """FR-13: any other role/endpoint combination -> 403."""
    with pytest.raises(AppError) as exc:
        ensure_student_access(ADMIN, "S1001")
    assert (exc.value.status_code, exc.value.code) == (403, "FORBIDDEN_ROLE")
