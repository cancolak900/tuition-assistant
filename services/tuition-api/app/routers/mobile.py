"""University Mobile App API (FR-01, FR-02).

No authentication. The limit of 3 calls per student per day is enforced by the API Gateway
(Kong rate-limiting keyed by the studentNo in the path), not by this service.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import STUDENT_NO_REGEX, TERM_REGEX, TuitionSummary, error_responses
from app.services.tuition import get_summary

router = APIRouter(prefix="/mobile", tags=["Mobile App"])

StudentNo = Annotated[str, Path(pattern=STUDENT_NO_REGEX, examples=["S1001"])]
Term = Annotated[str | None, Query(pattern=TERM_REGEX, description="YYYY-FALL or YYYY-SPRING; omit for the overall balance", examples=["2026-FALL"])]


@router.get(
    "/tuition/{studentNo}",
    response_model=TuitionSummary,
    response_model_by_alias=True,
    responses=error_responses(404, 422, 429),
    summary="Query tuition (no auth, 3 calls per student per day at the gateway)",
)
def query_tuition_mobile(studentNo: StudentNo, db: Annotated[Session, Depends(get_db)], term: Term = None) -> TuitionSummary:  # noqa: N803
    return get_summary(db, studentNo, term)
