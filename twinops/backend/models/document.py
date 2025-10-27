"""Document data model definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Document(BaseModel):
    id: str
    title: str
    source: str = Field(..., description="Source system identifier")
    uri: Optional[str] = Field(None, description="Reachable URI for the document")
    mime_type: str = "text/plain"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, str] = Field(default_factory=dict)
