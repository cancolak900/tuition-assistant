"""In-memory chat sessions (single agent instance; Redis would be the scale-out path).

A session belongs to the user who created it, keeps the recent message history for the LLM and
at most one pending payment action. Idle sessions expire.
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from app.errors import AppError


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Session:
    id: str
    user_id: int
    student_no: str
    history: list[Any] = field(default_factory=list)  # LLM-specific message objects
    pending: dict[str, Any] | None = None  # the single pending payment, if any
    completed_actions: dict[str, Any] = field(default_factory=dict)  # actionId -> payment result (idempotent /confirm)
    updated_at: datetime = field(default_factory=utcnow)


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
