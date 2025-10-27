"""Temporal workflow definition for employee onboarding."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow

from backend.workflows.activities import execute_runbook, notify_slack
from backend.workflows.templates.onboarding import ONBOARDING_WORKFLOW_TEMPLATE


@workflow.defn(name="workflows.onboarding.employee_onboarding")
class OnboardingWorkflow:
    """Coordinate onboarding messaging and checklist execution."""

    @workflow.run
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        employee = dict(payload)
        employee_name = employee.get("name") or employee.get("email") or "new hire"
        channel = employee.get("channel") or employee.get("manager_channel")

        welcome = await workflow.execute_activity(
            notify_slack,
            {
                "channel": channel,
                "text": f"👋 Welcoming {employee_name}! Onboarding checklist is now in progress.",
            },
            start_to_close_timeout=timedelta(minutes=1),
        )

        runbook = await workflow.execute_activity(
            execute_runbook,
            {
                "runbook_id": employee.get("runbook_id") or ONBOARDING_WORKFLOW_TEMPLATE["name"],
                "context": employee,
            },
            start_to_close_timeout=timedelta(minutes=5),
        )

        await workflow.execute_activity(
            notify_slack,
            {
                "channel": channel,
                "text": f"✅ Onboarding tasks for {employee_name} recorded. Mentor: {employee.get('mentor', 'TBD')}",
            },
            start_to_close_timeout=timedelta(minutes=1),
        )

        return {
            "employee": employee_name,
            "welcome": welcome,
            "runbook": runbook,
        }

