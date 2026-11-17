"""In-memory chat sessions (single agent instance; Redis would be the scale-out path).

A session belongs to the user who created it, keeps the recent message history for the LLM and
at most one pending payment action. Idle sessions expire.
"""

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.errors import AppError


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class PendingPayment:
    """A payment the LLM prepared. Only POST /confirm can execute it, always with this transactionId."""

    action: Any  # schemas.PendingAction, as shown to the user
    transaction_id: str

    @property
    def expired(self) -> bool:
        return utcnow() >= self.action.expires_at


@dataclass
class Session:
    id: str
    user_id: int
    student_no: str
    history: list[Any] = field(default_factory=list)  # LLM-specific message objects
    pending: PendingPayment | None = None  # at most one pending payment per session
    completed_actions: dict[str, Any] = field(default_factory=dict)  # actionId -> ConfirmResponse (repeat /confirm = same answer)
    language: str = "en"  # of the last clear user message; used for the fixed payment texts
    updated_at: datetime = field(default_factory=utcnow)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)


class SessionStore:
    def __init__(self, ttl: timedelta) -> None:
        self._ttl = ttl
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def _purge(self, now: datetime) -> None:
        for sid in [s.id for s in self._sessions.values() if now - s.updated_at > self._ttl]:
            del self._sessions[sid]

    def get_or_create(self, session_id: str | None, user_id: int, student_no: str) -> Session:
        now = utcnow()
        with self._lock:
            self._purge(now)
            if session_id is None:
                session = Session(id=uuid.uuid4().hex, user_id=user_id, student_no=student_no)
                self._sessions[session.id] = session
                return session
            session = self._sessions.get(session_id)
            # Someone else's session looks exactly like a missing one: no information leak.
            if session is None or session.user_id != user_id:
                raise AppError(404, "SESSION_NOT_FOUND", "Chat session not found or expired. Start a new conversation.")
            session.updated_at = now
            return session

    def get(self, session_id: str, user_id: int) -> Session:
        return self.get_or_create(session_id, user_id, "")

    def __len__(self) -> int:
        return len(self._sessions)
