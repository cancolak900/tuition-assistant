"""Verify the caller's JWT (defense in depth behind Kong) and keep the raw token for REST tool calls.

The agent has no credential of its own (FR-34): every REST call it makes on the user's behalf
reuses the exact bearer token the user sent.
"""

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.errors import AppError

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    username: str
    role: str
    student_no: str | None
    token: str  # forwarded unchanged to the gateway


def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise AppError(401, "UNAUTHORIZED", "Missing bearer token.")
    settings = get_settings()
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppError(401, "TOKEN_EXPIRED", "The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AppError(401, "INVALID_TOKEN", "The access token is invalid.") from exc
    return CurrentUser(int(claims["sub"]), str(claims.get("username", "")), str(claims.get("role")), claims.get("studentNo"), credentials.credentials)


def get_student(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
    """The chat assistant is for students: it always acts for the logged-in student only."""
    if user.role != "student" or not user.student_no:
        raise AppError(403, "FORBIDDEN_ROLE", "The assistant is available to students only.", {"role": user.role})
    return user


StudentDep = Annotated[CurrentUser, Depends(get_student)]
