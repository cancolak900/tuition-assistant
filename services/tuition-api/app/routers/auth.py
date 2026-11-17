"""Login (FR-10) and the current-user endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import User
from app.schemas import LoginRequest, MeResponse, TokenResponse
from app.security import CurrentUserDep, create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])

_ERRORS = {401: {"description": "Invalid credentials or token"}}


@router.post("/login", response_model=TokenResponse, response_model_by_alias=True, responses=_ERRORS, summary="Log in and get a JWT")
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == body.username))
    # verify_password also runs for unknown users, so both failures take the same time.
    if not verify_password(body.password, user.password_hash if user else None) or user is None:
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid username or password.")
    token, expires_in = create_access_token(user_id=user.id, username=user.username, role=user.role, student_no=user.student_no)
    return TokenResponse(access_token=token, expires_in=expires_in, role=user.role, student_no=user.student_no)


@router.get("/me", response_model=MeResponse, response_model_by_alias=True, responses=_ERRORS, summary="Who am I (decoded token)")
def me(user: CurrentUserDep) -> MeResponse:
    return MeResponse(user_id=user.user_id, username=user.username, role=user.role, student_no=user.student_no)
