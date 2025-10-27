"""Hybrid ranking logic for Graph-RAG results."""

from __future__ import annotations

from typing import Any, Dict, List


class HybridRanker:
    """Combine scores from graph, vector, and text sources."""

    def rank(
        self,
        graph_context: List[Dict[str, Any]],
        vector_results: List[Dict[str, Any]],
        text_results: List[Dict[str, Any]],
        weights: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        graph_scores = self._score_graph(graph_context)
        merged: Dict[str, Dict[str, Any]] = {}

        for result in vector_results:
            doc_id = result.get("id") or result.get("metadata", {}).get("document_id")
            merged.setdefault(doc_id, {"score": 0.0, "vector_score": 0.0, "text_score": 0.0, "graph_score": 0.0})
            merged[doc_id]["vector_score"] = result.get("score", 0.0)
            merged[doc_id]["metadata"] = result.get("metadata", {})

        for result in text_results:
            doc_id = result.get("metadata", {}).get("document_id") or result.get("id")
            merged.setdefault(doc_id, {"score": 0.0, "vector_score": 0.0, "text_score": 0.0, "graph_score": 0.0})
            merged[doc_id]["text_score"] = result.get("score", 0.0)
            merged[doc_id].setdefault("metadata", {}).update(result.get("metadata", {}))

        for doc_id, score in graph_scores.items():
            merged.setdefault(doc_id, {"score": 0.0, "vector_score": 0.0, "text_score": 0.0, "graph_score": 0.0})
            merged[doc_id]["graph_score"] = score

        for doc_id, payload in merged.items():
            payload["score"] = (
                payload["graph_score"] * weights.get("graph", 0)
                + payload["vector_score"] * weights.get("vector", 0)
                + payload["text_score"] * weights.get("text", 0)
            )
            payload["document_id"] = doc_id

        return sorted(merged.values(), key=lambda item: item["score"], reverse=True)

    def _score_graph(self, graph_context: List[Dict[str, Any]]) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        for ctx in graph_context:
            for node in ctx.get("nodes", []):
                scores[node] = scores.get(node, 0.0) + 1.0
        return scores
