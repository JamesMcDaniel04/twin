from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, EmailStr, Field


class User(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
    attributes: Dict[str, Any] = Field(default_factory=dict)
    clearance_level: int = 0
    last_active_at: Optional[datetime] = None
