"""Response data model definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class Citation(BaseModel):
    document_id: str
    snippet: str
    score: float


class QueryResponse(BaseModel):
    id: str
    query_id: str
    content: str
    citations: List[Citation] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
