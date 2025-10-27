"""Temporal workflow definition for incident response."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow

from backend.models.incident import SeverityLevel
from backend.workflows.activities import (
    assess_severity,
    create_jira_ticket,
    execute_runbook,
    notify_slack,
    page_on_call_engineer,
    schedule_postmortem,
    update_jira_ticket,
)


def _as_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return {}


@workflow.defn(name="workflows.incident.handle_incident")
class IncidentWorkflow:
    """Coordinate notification, ticketing, and automation for incidents."""

    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        incident = _as_dict(payload.get("incident"))

        severity_result = await workflow.execute_activity(
            assess_severity,
            incident,
            start_to_close_timeout=timedelta(seconds=30),
        )
        severity_value = int(severity_result)

        slack_payload = {
            "channel": payload.get("channel") or incident.get("channel"),
            "text": (
                f":rotating_light: Incident {incident.get('title', 'unknown')} reported.\n"
                f"Severity: {SeverityLevel(severity_value).name.title()}\n"
                f"Systems: {', '.join(incident.get('impacted_systems', [])) or 'n/a'}"
            ),
        }

        slack_result = await workflow.execute_activity(
            notify_slack,
            slack_payload,
            start_to_close_timeout=timedelta(minutes=1),
        )

        ticket_id = await workflow.execute_activity(
            create_jira_ticket,
            incident,
            start_to_close_timeout=timedelta(minutes=2),
        )

        if incident.get("runbook_id"):
            await workflow.execute_activity(
                execute_runbook,
                {"runbook_id": incident["runbook_id"], "context": incident},
                start_to_close_timeout=timedelta(minutes=5),
            )

        if severity_value >= SeverityLevel.HIGH.value:
            await workflow.execute_activity(
                page_on_call_engineer,
                incident,
                start_to_close_timeout=timedelta(minutes=1),
            )

        postmortem_id = await workflow.execute_activity(
            schedule_postmortem,
            incident,
            start_to_close_timeout=timedelta(minutes=1),
        )

        await workflow.execute_activity(
            update_jira_ticket,
            {
                "ticket_id": ticket_id,
                "comment": f"Postmortem scheduled under reference {postmortem_id}",
            },
            start_to_close_timeout=timedelta(minutes=1),
        )

        return {
            "ticket_id": ticket_id,
            "severity": severity_value,
            "slack_notification": slack_result,
            "postmortem_id": postmortem_id,
        }

