from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Role(BaseModel):
    id: str
    name: str
    department: str
    level: str  # junior, mid, senior, lead, manager
    responsibilities: List[str]
    required_skills: List[str]
    delegation_chain: List[str]  # Role IDs
    knowledge_domains: List[str]
    created_at: datetime
    updated_at: datetime
    is_active: bool = Field(default=True)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Person(BaseModel):
    id: str
    name: str
    email: str
    slack_id: str
    current_role_id: Optional[str]
    past_roles: List[Dict[str, Any]] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    availability_status: str  # available, busy, ooo, offline
    timezone: str
    created_at: datetime


class Document(BaseModel):
    id: str
    title: str
    source: str  # slack, gdrive, confluence, etc.
    source_url: str
    content_hash: str
    role_owner_id: str
    project_id: Optional[str]
    classification: str  # public, internal, confidential, secret
    last_modified: datetime
    embedding_ids: List[str] = Field(default_factory=list)
    chunk_count: int
    metadata: Dict[str, Any] = Field(default_factory=dict)
