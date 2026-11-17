"""Passwords (bcrypt), JWT issue/verify, and the authentication/authorization dependencies.

Rules (docs/02_Technical_Design.md §6):
- A valid JWT is required for every banking and admin operation.
- role "bank" may act for any student; role "student" only for its own studentNo; role "admin" only on /admin.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.errors import AppError

ALGORITHM = "HS256"
ROLE_STUDENT, ROLE_BANK, ROLE_ADMIN = "student", "bank", "admin"

# A real bcrypt hash of a random string: checking against it keeps the response time of
# "unknown user" equal to "wrong password", so usernames cannot be discovered by timing.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt()).decode("ascii")


# ---------- passwords ----------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str | None) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), (hashed or _DUMMY_HASH).encode("ascii")) and hashed is not None
    except ValueError:  # malformed hash
        return False


# ---------- tokens ----------

@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    role: str
    student_no: str | None


def create_access_token(*, user_id: int, username: str, role: str, student_no: str | None) -> tuple[str, int]:
    """Return (token, lifetime in seconds)."""
    settings = get_settings()
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.jwt_expires_min)
    claims: dict[str, Any] = {
        "iss": settings.jwt_issuer,  # Kong's jwt plugin looks the signing secret up by this claim
        "sub": str(user_id),
        "username": username,
        "role": role,
        "studentNo": student_no,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=ALGORITHM), int(lifetime.total_seconds())


def decode_token(token: str) -> CurrentUser:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[ALGORITHM],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("TOKEN_EXPIRED", "The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized("INVALID_TOKEN", "The access token is invalid.") from exc

    role = claims.get("role")
    if role not in (ROLE_STUDENT, ROLE_BANK, ROLE_ADMIN) or (role == ROLE_STUDENT and not claims.get("studentNo")):
        raise _unauthorized("INVALID_TOKEN", "The access token is invalid.")
    return CurrentUser(int(claims["sub"]), str(claims.get("username", "")), role, claims.get("studentNo"))


def _unauthorized(code: str, message: str) -> AppError:
    return AppError(401, code, message)


# ---------- FastAPI dependencies ----------

_bearer = HTTPBearer(auto_error=False)


def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise _unauthorized("UNAUTHORIZED", "Missing bearer token.")
    return decode_token(credentials.credentials)


def require_roles(*roles: str):
    """Dependency factory: the caller must be authenticated and have one of `roles`."""

    def _dependency(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        if user.role not in roles:
            raise AppError(403, "FORBIDDEN_ROLE", "This operation is not allowed for your role.", {"role": user.role, "allowed": list(roles)})
        return user

    return _dependency


def ensure_student_access(user: CurrentUser, student_no: str) -> None:
    """Banking rule (FR-12, FR-13): bank -> any student; student -> only itself; anything else -> 403."""
    if user.role == ROLE_BANK:
        return
    if user.role == ROLE_STUDENT and user.student_no == student_no:
        return
    if user.role == ROLE_STUDENT:
        raise AppError(403, "FORBIDDEN_OTHER_STUDENT", "You can only access your own tuition records.")
    raise AppError(403, "FORBIDDEN_ROLE", "This operation is not allowed for your role.", {"role": user.role, "allowed": [ROLE_STUDENT, ROLE_BANK]})


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
