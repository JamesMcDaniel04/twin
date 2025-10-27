"""Session state management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

from backend.orchestration.cache import cache


@dataclass
class SessionState:
    session_id: str
    user_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=1))
    metadata: Dict[str, str] = field(default_factory=dict)


class SessionStore:
    """Persist session state via cache backend."""

    async def save(self, state: SessionState) -> None:
        await cache.set(
            self._key(state.session_id),
            {
                "session_id": state.session_id,
                "user_id": state.user_id,
                "created_at": state.created_at.isoformat(),
                "expires_at": state.expires_at.isoformat(),
                "metadata": state.metadata,
            },
            ttl=int((state.expires_at - datetime.utcnow()).total_seconds()),
        )

    async def load(self, session_id: str) -> Optional[SessionState]:
        payload = await cache.get(self._key(session_id))
        if not payload:
            return None

        return SessionState(
            session_id=payload["session_id"],
            user_id=payload["user_id"],
            created_at=datetime.fromisoformat(payload["created_at"]),
            expires_at=datetime.fromisoformat(payload["expires_at"]),
            metadata=payload.get("metadata", {}),
        )

    async def delete(self, session_id: str) -> None:
        await cache.delete(self._key(session_id))

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}"


session_store = SessionStore()
