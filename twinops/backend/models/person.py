"""Person data model definitions."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class Person(BaseModel):
    id: str = Field(..., description="Unique person identifier")
    name: str
    email: EmailStr
    roles: List[str] = Field(default_factory=list, description="Role IDs the person fills")
    avatar_url: Optional[str] = None
    metadata: Dict[str, str] = Field(default_factory=dict)
