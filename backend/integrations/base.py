"""Base integration abstraction."""

from __future__ import annotations

from typing import Any, Dict


class IntegrationBase:
    """Common interface for external integrations."""

    name: str = "integration"

    async def send_event(self, payload: Dict[str, Any]) -> None:
        raise NotImplementedError
