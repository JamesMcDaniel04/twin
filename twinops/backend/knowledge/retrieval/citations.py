from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Citation:
    source_id: str
    document_name: str
    page_number: Optional[int]
    confidence_score: float
    timestamp: datetime
    direct_link: str
