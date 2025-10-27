"""Workflow and activity registry for Temporal workers."""

from __future__ import annotations

from typing import Iterable

from backend.workflows import activities
from backend.workflows.incident import IncidentWorkflow
from backend.workflows.onboarding import OnboardingWorkflow
from backend.workflows.release import ReleaseWorkflow


def workflows() -> Iterable[object]:
    return [IncidentWorkflow, ReleaseWorkflow, OnboardingWorkflow]


def activities_list() -> Iterable[object]:
    return [
        activities.notify_slack,
        activities.create_jira_ticket,
        activities.update_jira_ticket,
        activities.execute_runbook,
        activities.persist_snapshot,
        activities.assess_severity,
        activities.page_on_call_engineer,
        activities.schedule_postmortem,
    ]


__all__ = ["workflows", "activities_list"]

