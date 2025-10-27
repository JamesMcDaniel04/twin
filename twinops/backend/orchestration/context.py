"""Context management for TwinOps orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from backend.orchestration.cache import cache


@dataclass
class ContextWindow:
    session_id: str
    messages: List[Dict[str, str]] = field(default_factory=list)
    max_messages: int = 20

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]


class ContextManager:
    """Persist context windows per active session."""

    async def get(self, session_id: str) -> ContextWindow:
        payload = await cache.get(self._key(session_id))
        if not payload:
            return ContextWindow(session_id=session_id)
        return ContextWindow(session_id=session_id, messages=payload.get("messages", []))

    async def save(self, window: ContextWindow) -> None:
        await cache.set(self._key(window.session_id), {"messages": window.messages}, ttl=3600)

    def _key(self, session_id: str) -> str:
        return f"context:{session_id}"


context_manager = ContextManager()
