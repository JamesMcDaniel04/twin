from __future__ import annotations

from datetime import datetime
from enum import IntEnum
from typing import List, Optional

from pydantic import BaseModel, Field


class SeverityLevel(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class IncidentInput(BaseModel):
    incident_id: str
    title: str
    description: str
    reported_at: datetime
    reported_by: str
    impacted_systems: List[str] = Field(default_factory=list)
    severity_hint: Optional[SeverityLevel] = None
    has_runbook: bool = False
    runbook_id: Optional[str] = None
    context: dict = Field(default_factory=dict)


class IncidentResult(BaseModel):
    ticket_id: str
    status: str
    acknowledgements: List[str] = Field(default_factory=list)
    escalated_to: Optional[str] = None
