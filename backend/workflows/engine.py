"""Temporal workflow engine integration."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Dict

from temporalio.client import Client  # type: ignore

from backend.core.config import settings

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Lightweight wrapper around the Temporal client."""

    def __init__(self) -> None:
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self) -> Client:
        if self._client:
            return self._client

        async with self._lock:
            if not self._client:
                try:
                    self._client = await Client.connect(settings.TEMPORAL_HOST, namespace=settings.TEMPORAL_NAMESPACE)
                except Exception as exc:  # pragma: no cover - Temporal not available in tests
                    logger.warning("Temporal connection failed: %s", exc)
                    raise
        return self._client

    async def start_workflow(self, workflow: str, payload: Dict[str, Any]) -> str:
        """Start a workflow run and return its run_id."""

        workflow_name = self._resolve_workflow(workflow)
        try:
            client = await self._ensure_client()
        except Exception:
            # Fallback when Temporal is not reachable (development/testing)
            return f"{workflow}-{uuid.uuid4()}"

        handle = await client.start_workflow(
            workflow_name,
            payload,
            id=str(uuid.uuid4()),
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
        return handle.first_execution_run_id

    def _resolve_workflow(self, workflow: str) -> str:
        mapping = {
            "incident": "workflows.incident.handle_incident",
            "release": "workflows.release.manage_release",
            "onboarding": "workflows.onboarding.employee_onboarding",
        }

        if workflow not in mapping:
            raise ValueError(f"Unknown workflow '{workflow}'")
        return mapping[workflow]


workflow_engine = WorkflowEngine()
