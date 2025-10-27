"""Temporal workflow definition for release management."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow

from backend.workflows.activities import execute_runbook, notify_slack, update_jira_ticket
from backend.workflows.templates.release import RELEASE_WORKFLOW_TEMPLATE


@workflow.defn(name="workflows.release.manage_release")
class ReleaseWorkflow:
    """Orchestrate release announcements and automated runbooks."""

    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        release = dict(payload)
        release_id = release.get("release_id") or f"release-{uuid.uuid4().hex[:6]}"
        channel = release.get("channel") or release.get("announcement_channel")

        start_message = await workflow.execute_activity(
            notify_slack,
            {
                "channel": channel,
                "text": f":rocket: Release {release_id} has started."
                f"\nScope: {release.get('scope', 'n/a')}",
            },
            start_to_close_timeout=timedelta(minutes=1),
        )

        runbook_result = await workflow.execute_activity(
            execute_runbook,
            {
                "runbook_id": release.get("runbook_id") or RELEASE_WORKFLOW_TEMPLATE["name"],
                "context": release,
            },
            start_to_close_timeout=timedelta(minutes=10),
        )

        await workflow.execute_activity(
            notify_slack,
            {
                "channel": channel,
                "text": f"✅ Release {release_id} completed successfully.",
            },
            start_to_close_timeout=timedelta(minutes=1),
        )

        if release.get("ticket_id"):
            await workflow.execute_activity(
                update_jira_ticket,
                {
                    "ticket_id": release["ticket_id"],
                    "comment": f"Release {release_id} completed. Steps executed: {len(runbook_result.get('steps', []))}",
                },
                start_to_close_timeout=timedelta(minutes=1),
            )

        return {
            "release_id": release_id,
            "notifications": start_message,
            "runbook": runbook_result,
        }

