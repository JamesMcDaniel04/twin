"""Citations builder for TwinOps responses."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.models.document import Document


class CitationBuilder:
    """Attach citation metadata to ranked results."""

    def build(self, ranked_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for item in ranked_results:
            metadata = item.get("metadata", {})
            document = Document(
                id=item.get("document_id", metadata.get("document_id", "unknown")),
                title=metadata.get("title", "Untitled"),
                source=metadata.get("source", "unknown"),
                uri=metadata.get("uri"),
                metadata=metadata,
            )
            results.append(
                {
                    "document": document,
                    "score": item.get("score", 0.0),
                    "snippet": metadata.get("snippet", ""),
                    "summary": metadata.get("summary", metadata.get("content", ""))[:500],
                }
            )
        return results
