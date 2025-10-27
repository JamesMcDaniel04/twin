"""Workflow activity implementations."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from temporalio import activity

from backend.core.config import settings
from backend.core.database import database_manager
from backend.integrations.jira import jira_integration
from backend.models.incident import IncidentInput, SeverityLevel
from backend.workflows.templates.incident import INCIDENT_WORKFLOW_TEMPLATE
from backend.workflows.templates.onboarding import ONBOARDING_WORKFLOW_TEMPLATE
from backend.workflows.templates.release import RELEASE_WORKFLOW_TEMPLATE

try:  # pragma: no cover - optional dependency during tests
    from slack_sdk.web.async_client import AsyncWebClient
except ImportError:  # pragma: no cover - Slack optional
    AsyncWebClient = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class ActivitiesContext:
    """Holds lazily-instantiated clients used by workflow activities."""

    slack_client: Optional["AsyncWebClient"] = None
    default_slack_channel: str = "#incidents"
    oncall_channel: str = "#on-call"
    jira_project: str = "OPS"
    playbooks: Dict[str, List[str]] = field(default_factory=dict)


_context: Optional[ActivitiesContext] = None


def get_activities_context() -> ActivitiesContext:
    global _context
    if _context is not None:
        return _context

    slack_client = None
    if AsyncWebClient and settings.SLACK_BOT_TOKEN:
        slack_client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)

    _context = ActivitiesContext(
        slack_client=slack_client,
        default_slack_channel=getattr(settings, "INCIDENT_SLACK_CHANNEL", "#incidents"),
        oncall_channel=getattr(settings, "ONCALL_SLACK_CHANNEL", "#on-call"),
        jira_project=getattr(settings, "JIRA_PROJECT_KEY", "OPS"),
        playbooks=_build_playbook_catalog(),
    )
    return _context


def _build_playbook_catalog() -> Dict[str, List[str]]:
    catalog: Dict[str, List[str]] = {
        INCIDENT_WORKFLOW_TEMPLATE["name"]: INCIDENT_WORKFLOW_TEMPLATE["steps"],
        RELEASE_WORKFLOW_TEMPLATE["name"]: RELEASE_WORKFLOW_TEMPLATE["steps"],
        ONBOARDING_WORKFLOW_TEMPLATE["name"]: ONBOARDING_WORKFLOW_TEMPLATE["steps"],
    }
    # Friendly aliases
    catalog.setdefault("incident", INCIDENT_WORKFLOW_TEMPLATE["steps"])
    catalog.setdefault("release", RELEASE_WORKFLOW_TEMPLATE["steps"])
    catalog.setdefault("onboarding", ONBOARDING_WORKFLOW_TEMPLATE["steps"])
    return catalog


def _normalize_incident(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, IncidentInput):
        return payload.model_dump()
    if isinstance(payload, dict):
        return dict(payload)
    raise TypeError(f"Unsupported incident payload type: {type(payload)!r}")


async def _notify_slack_impl(payload: Dict[str, Any]) -> Dict[str, Any]:
    ctx = get_activities_context()
    channel = payload.get("channel") or ctx.default_slack_channel
    text = payload.get("text") or payload.get("message")
    if not text:
        raise ValueError("Slack notification payload requires 'text'.")

    if ctx.slack_client is None:
        logger.warning("Slack client unavailable; logging notification. channel=%s text=%s", channel, text)
        return {"status": "queued", "channel": channel, "text": text}

    try:
        response = await ctx.slack_client.chat_postMessage(
            channel=channel,
            text=text,
            blocks=payload.get("blocks"),
            thread_ts=payload.get("thread_ts"),
        )
    except Exception as exc:  # pragma: no cover - Slack API errors
        logger.error("Failed to send Slack notification: %s", exc)
        raise

    ts = response.get("ts") if isinstance(response, dict) else None
    return {"status": "sent", "channel": channel, "ts": ts, "text": text}


async def _create_jira_ticket_impl(payload: Any) -> str:
    incident = _normalize_incident(payload)
    project_key = incident.get("project_key") or get_activities_context().jira_project
    issue_type = incident.get("issue_type", "Incident")
    summary = incident.get("title") or "Operational Incident"
    description = incident.get("description") or "Automated incident capture"

    event = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
            "labels": incident.get("labels", []),
        }
    }

    await jira_integration.send_event(event)
    ticket_hint = incident.get("ticket_id")
    return ticket_hint or f"{project_key}-{uuid.uuid4().hex[:8]}"


async def _update_jira_ticket_impl(payload: Dict[str, Any]) -> None:
    ticket_id = payload.get("ticket_id")
    comment = payload.get("comment")
    if not ticket_id or not comment:
        return

    if not jira_integration.base_url or not jira_integration.api_token:
        logger.warning("Jira integration not configured; skipping ticket update for %s", ticket_id)
        return

    url = f"{jira_integration.base_url}/rest/api/3/issue/{ticket_id}/comment"
    headers = {
        "Authorization": f"Bearer {jira_integration.api_token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(url, json={"body": comment}, headers=headers)
    except Exception as exc:  # pragma: no cover - network errors
        logger.error("Failed to update Jira ticket %s: %s", ticket_id, exc)
        raise


async def _execute_runbook_impl(request: Any) -> Dict[str, Any]:
    if isinstance(request, str):
        runbook_id = request
        context: Dict[str, Any] = {}
    elif isinstance(request, dict):
        runbook_id = request.get("runbook_id")
        context = request.get("context", {}) or {}
    else:
        raise TypeError(f"Unsupported runbook request: {type(request)!r}")

    ctx = get_activities_context()
    steps = ctx.playbooks.get(runbook_id) or []
    if not steps:
        logger.warning("Runbook '%s' not found; skipping execution.", runbook_id)
        return {"runbook_id": runbook_id, "status": "not_found", "steps": []}

    execution_log: List[Dict[str, Any]] = []
    for step in steps:
        logger.info("Executing runbook '%s' step '%s'", runbook_id, step)
        await asyncio.sleep(0)
        execution_log.append(
            {
                "step": step,
                "status": "completed",
                "completed_at": datetime.utcnow().isoformat(),
            }
        )

    await _persist_snapshot_impl(
        {
            "type": "runbook_execution",
            "runbook_id": runbook_id,
            "context": context,
            "steps": execution_log,
        }
    )

    return {"runbook_id": runbook_id, "status": "completed", "steps": execution_log}


async def _persist_snapshot_impl(payload: Dict[str, Any]) -> None:
    mongodb = database_manager.mongodb
    if mongodb is None:
        logger.warning("MongoDB unavailable; snapshot skipped: %s", payload)
        return

    document = dict(payload)
    document.setdefault("created_at", datetime.utcnow())
    try:
        await mongodb["twinops"]["workflow_snapshots"].insert_one(document)
    except Exception as exc:  # pragma: no cover - database errors
        logger.error("Failed to persist workflow snapshot: %s", exc)


async def _assess_severity_impl(payload: Any) -> SeverityLevel:
    incident = _normalize_incident(payload)
    hint = incident.get("severity_hint")
    if hint is not None:
        return SeverityLevel(int(hint))

    score = SeverityLevel.LOW.value
    impacted = incident.get("impacted_systems") or []
    if len(impacted) >= 3:
        score += 1

    description = (incident.get("description") or "").lower()
    if any(keyword in description for keyword in ("outage", "critical", "data loss", "sev1")):
        score += 1

    return SeverityLevel(min(score, SeverityLevel.CRITICAL.value))


async def _page_on_call_engineer_impl(payload: Any) -> str:
    incident = _normalize_incident(payload)
    ctx = get_activities_context()
    channel = incident.get("oncall_channel") or ctx.oncall_channel
    message = (
        f":rotating_light: Incident {incident.get('incident_id', 'unknown')} requires attention.\n"
        f"Severity hint: {incident.get('severity_hint') or 'TBD'}\n"
        f"Impacted systems: {', '.join(incident.get('impacted_systems', [])) or 'n/a'}"
    )
    response = await _notify_slack_impl({"channel": channel, "text": message})
    return response.get("ts", f"ack-{uuid.uuid4().hex[:6]}")


async def _schedule_postmortem_impl(payload: Any) -> str:
    incident = _normalize_incident(payload)
    meeting_id = f"postmortem-{uuid.uuid4().hex[:6]}"
    scheduled_at = incident.get("postmortem_time") or (datetime.utcnow() + timedelta(days=1)).isoformat()

    await _persist_snapshot_impl(
        {
            "type": "postmortem_schedule",
            "meeting_id": meeting_id,
            "incident_id": incident.get("incident_id"),
            "scheduled_at": scheduled_at,
            "owner": incident.get("reported_by"),
        }
    )

    return meeting_id


@activity.defn
async def notify_slack(payload: Dict[str, Any]) -> Dict[str, Any]:
    return await _notify_slack_impl(payload)


@activity.defn
async def create_jira_ticket(payload: Any) -> str:
    return await _create_jira_ticket_impl(payload)


@activity.defn
async def update_jira_ticket(payload: Dict[str, Any]) -> None:
    await _update_jira_ticket_impl(payload)


@activity.defn
async def execute_runbook(request: Any) -> Dict[str, Any]:
    return await _execute_runbook_impl(request)


@activity.defn
async def persist_snapshot(payload: Dict[str, Any]) -> None:
    await _persist_snapshot_impl(payload)


@activity.defn
async def assess_severity(payload: Any) -> SeverityLevel:
    return await _assess_severity_impl(payload)


@activity.defn
async def page_on_call_engineer(payload: Any) -> str:
    return await _page_on_call_engineer_impl(payload)


@activity.defn
async def schedule_postmortem(payload: Any) -> str:
    return await _schedule_postmortem_impl(payload)


__all__ = [
    "ActivitiesContext",
    "get_activities_context",
    "notify_slack",
    "create_jira_ticket",
    "update_jira_ticket",
    "execute_runbook",
    "persist_snapshot",
    "assess_severity",
    "page_on_call_engineer",
    "schedule_postmortem",
]

