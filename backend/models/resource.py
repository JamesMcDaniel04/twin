from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field


class Resource(BaseModel):
    id: str
    type: str
    attributes: Dict[str, Any] = Field(default_factory=dict)
    classification: int = 0
