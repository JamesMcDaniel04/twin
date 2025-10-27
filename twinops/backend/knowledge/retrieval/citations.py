from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class Citation:
    source_id: str
    document_name: str
    page_number: Optional[int]
    confidence_score: float
    timestamp: datetime
    direct_link: str


class CitationBuilder:
    """Legacy helper to map ranked results to citation dictionaries."""

    def build(self, ranked_results: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        mapped: List[Dict[str, Any]] = []
        for result in ranked_results:
            metadata = result.get("metadata", {})
            mapped.append(
                {
                    "document": {
                        "id": result.get("document_id"),
                        "title": metadata.get("title"),
                        "source": metadata.get("source"),
                        "direct_link": metadata.get("direct_link"),
                    },
                    "score": result.get("score", 0.0),
                    "snippet": metadata.get("summary") or metadata.get("snippet", ""),
                }
            )
        return mapped


__all__ = ["Citation", "CitationBuilder"]
