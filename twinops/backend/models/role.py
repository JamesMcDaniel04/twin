"""Role data model definitions."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Role(BaseModel):
    id: str = Field(..., description="Unique role identifier")
    name: str
    description: Optional[str] = None
    responsibilities: List[str] = Field(default_factory=list)
    delegations: List[str] = Field(default_factory=list, description="Role IDs this role delegates to")
    metadata: Dict[str, str] = Field(default_factory=dict)
