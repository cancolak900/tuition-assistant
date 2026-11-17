"""University Web Site - Admin API (FR-07..FR-09). Requires a JWT with role admin."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    TERM_REGEX,
    AddTuitionRequest,
    AddTuitionResponse,
    BatchResponse,
    UnpaidPage,
    error_responses,
)
from app.security import ROLE_ADMIN, CurrentUser, require_roles
from app.services.admin import add_tuition, add_tuition_batch, unpaid_tuitions

router = APIRouter(prefix="/admin", tags=["Admin"])

AdminUser = Annotated[CurrentUser, Depends(require_roles(ROLE_ADMIN))]
DB = Annotated[Session, Depends(get_db)]


@router.post(
    "/tuition",
    status_code=201,
    response_model=AddTuitionResponse,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    responses={200: {"model": AddTuitionResponse, "description": "Existing record updated"}, **error_responses(401, 403, 404, 409, 422)},
    summary="Add or update tuition for a student and term (201 CREATED / 200 UPDATED)",
)
def create_or_update_tuition(body: AddTuitionRequest, _: AdminUser, db: DB, response: Response) -> AddTuitionResponse:
    result = add_tuition(db, body)
    if result.status == "UPDATED":
        response.status_code = 200
    return result


@router.post(
    "/tuition/batch",
    response_model=BatchResponse,
    response_model_by_alias=True,
    responses=error_responses(400, 401, 403),
    summary="Add tuition from a CSV file (header: studentNo,term,amount,currency)",
)
async def upload_tuition_batch(_: AdminUser, db: DB, file: Annotated[UploadFile, File(description="UTF-8 CSV file")]) -> BatchResponse:
    return add_tuition_batch(db, await file.read())


@router.get(
    "/tuition/unpaid",
    response_model=UnpaidPage,
    response_model_by_alias=True,
    responses=error_responses(401, 403, 422),
    summary="Paged list of students with an unpaid balance for a term",
)
def list_unpaid(
    _: AdminUser,
    db: DB,
    term: Annotated[str, Query(pattern=TERM_REGEX, examples=["2026-FALL"])],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 10,
) -> UnpaidPage:
    return unpaid_tuitions(db, term, page, page_size)
