"""Agent orchestrator: owns sessions and turns a chat message into a reply plus a tool trace.

The LLM loop, the MCP/REST tools and the payment confirmation flow plug into this class.
"""

from datetime import timedelta

from app.config import Settings
from app.errors import AppError
from app.schemas import ChatResponse, ConfirmResponse
from app.security import CurrentUser
from app.sessions import SessionStore


class Agent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sessions = SessionStore(timedelta(minutes=settings.session_ttl_minutes))

    async def chat(self, user: CurrentUser, session_id: str | None, message: str) -> ChatResponse:
        session = self.sessions.get_or_create(session_id, user.user_id, user.student_no)
        return ChatResponse(
            session_id=session.id,
            reply="The assistant is running, but it is not connected to the language model yet.",
            trace=[],
        )

    async def confirm(self, user: CurrentUser, session_id: str, action_id: str, decision: str) -> ConfirmResponse:
        session = self.sessions.get(session_id, user.user_id)
        if session.pending is None or session.pending.get("actionId") != action_id:
            raise AppError(404, "ACTION_NOT_FOUND", "There is no pending action with this id.")
        raise AppError(501, "NOT_IMPLEMENTED", "Payment confirmation is not available yet.")
