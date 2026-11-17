"""Chat and payment-confirmation endpoints (behind Kong; JWT with role student)."""

from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.agent import Agent
from app.config import get_settings
from app.schemas import ChatRequest, ChatResponse, ConfirmRequest, ConfirmResponse
from app.security import StudentDep

router = APIRouter(tags=["Agent"])


class _Error(BaseModel):
    error: dict[str, Any]


ERRORS = {401: {"model": _Error, "description": "Missing or invalid token"}, 403: {"model": _Error, "description": "Not a student"},
          404: {"model": _Error, "description": "Session or action not found"}, 422: {"model": _Error, "description": "Validation error"}}


@lru_cache
def get_agent() -> Agent:
    return Agent(get_settings())


AgentDep = Annotated[Agent, Depends(get_agent)]


@router.post("/chat", response_model=ChatResponse, response_model_by_alias=True, responses=ERRORS, summary="Send a message to the assistant")
async def chat(body: ChatRequest, user: StudentDep, agent: AgentDep) -> ChatResponse:
    return await agent.chat(user, body.session_id, body.message)


@router.post("/confirm", response_model=ConfirmResponse, response_model_by_alias=True, responses=ERRORS, summary="Confirm or cancel a pending payment")
async def confirm(body: ConfirmRequest, user: StudentDep, agent: AgentDep) -> ConfirmResponse:
    return await agent.confirm(user, body.session_id, body.action_id, body.decision)


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}
