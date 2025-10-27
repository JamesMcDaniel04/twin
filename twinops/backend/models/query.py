"""Query data model definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Query(BaseModel):
    id: str
    text: str
    embedding: Optional[List[float]] = None
    context: Dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Priority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Query(BaseModel):
    id: str
    content: str
    created_at: datetime
    priority: Priority = Priority.MEDIUM
    required_skills: List[str] = Field(default_factory=list)
    context: Dict[str, str] = Field(default_factory=dict)
    source: Optional[str] = None
