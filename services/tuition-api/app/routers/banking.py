"""Banking App API (FR-03..FR-06). Requires a JWT: role bank (any student) or student (itself only)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.mobile import StudentNo, Term
from app.schemas import TuitionSummary, error_responses
from app.security import ROLE_BANK, ROLE_STUDENT, CurrentUser, ensure_student_access, require_roles
from app.services.tuition import get_summary

router = APIRouter(prefix="/banking", tags=["Banking App"])

BankingUser = Annotated[CurrentUser, Depends(require_roles(ROLE_BANK, ROLE_STUDENT))]


@router.get(
    "/tuition/{studentNo}",
    response_model=TuitionSummary,
    response_model_by_alias=True,
    responses=error_responses(401, 403, 404, 422),
    summary="Query tuition (bank: any student, student: own records only)",
)
def query_tuition_banking(studentNo: StudentNo, user: BankingUser, db: Annotated[Session, Depends(get_db)], term: Term = None) -> TuitionSummary:  # noqa: N803
    ensure_student_access(user, studentNo)
    return get_summary(db, studentNo, term)
