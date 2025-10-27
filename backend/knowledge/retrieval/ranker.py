"""Hybrid ranking logic for Graph-RAG results."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence


@dataclass
class RankingExperimentResult:
    """Outcome metrics for a single weight experiment."""

    weights: Dict[str, float]
    score: float
    coverage: float
    diversity: float
    top_documents: List[str]


class HybridRanker:
    """Combine scores from graph, vector, and text sources with feedback-aware tuning."""

    def __init__(self, default_weights: Optional[Dict[str, float]] = None) -> None:
        self.weights: Dict[str, float] = default_weights or {"graph": 0.35, "vector": 0.5, "text": 0.15}

    def rank(
        self,
        graph_context: List[Dict[str, Any]],
        vector_results: List[Dict[str, Any]],
        text_results: List[Dict[str, Any]],
        weights: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        weights = weights or self.weights
        graph_scores = self._score_graph(graph_context)
        merged: Dict[str, Dict[str, Any]] = {}

        for result in vector_results:
            doc_id = result.get("document_id") or result.get("id") or result.get("metadata", {}).get("document_id")
            if doc_id is None:
                continue
            merged.setdefault(doc_id, self._empty_payload())
            merged[doc_id]["vector_score"] = float(result.get("score", 0.0))
            merged[doc_id]["metadata"] = result.get("metadata", {})

        for result in text_results:
            doc_id = result.get("document_id") or result.get("metadata", {}).get("document_id") or result.get("id")
            if doc_id is None:
                continue
            merged.setdefault(doc_id, self._empty_payload())
            merged[doc_id]["text_score"] = float(result.get("score", 0.0))
            merged[doc_id].setdefault("metadata", {}).update(result.get("metadata", {}))

        for doc_id, score in graph_scores.items():
            merged.setdefault(doc_id, self._empty_payload())
            merged[doc_id]["graph_score"] = score

        total_weight = sum(weights.values()) or 1.0
        for doc_id, payload in merged.items():
            component_scores = {
                "graph": payload["graph_score"],
                "vector": payload["vector_score"],
                "text": payload["text_score"],
            }
            payload["score"] = sum(component_scores[key] * weights.get(key, 0.0) for key in component_scores)
            payload["document_id"] = doc_id
            payload["component_scores"] = component_scores
            payload["confidence"] = self._compute_confidence(component_scores, weights, total_weight)

        return sorted(merged.values(), key=lambda item: item["score"], reverse=True)

    def run_experiments(
        self,
        graph_context: List[Dict[str, Any]],
        vector_results: List[Dict[str, Any]],
        text_results: List[Dict[str, Any]],
        *,
        candidate_weights: Optional[Sequence[Dict[str, float]]] = None,
        judge: Optional[Callable[[List[Dict[str, Any]]], float]] = None,
        top_k: int = 5,
    ) -> List[RankingExperimentResult]:
        """Evaluate multiple weight combinations and update the default weights."""

        candidates = candidate_weights or list(self._generate_candidate_weights())
        experiments: List[RankingExperimentResult] = []

        for candidate in candidates:
            ranked = self.rank(graph_context, vector_results, text_results, candidate)
            score, coverage, diversity = self._evaluate(ranked[:top_k], graph_context, judge)
            experiments.append(
                RankingExperimentResult(
                    weights=candidate,
                    score=score,
                    coverage=coverage,
                    diversity=diversity,
                    top_documents=[item.get("document_id") for item in ranked[:top_k]],
                )
            )

        if experiments:
            best = max(experiments, key=lambda item: item.score)
            self.weights = dict(best.weights)

        return experiments

    def update_default_weights(self, new_weights: Dict[str, float]) -> None:
        """Persist normalized weights as the new default configuration."""

        total = sum(new_weights.values()) or 1.0
        self.weights = {component: value / total for component, value in new_weights.items()}

    def _score_graph(self, graph_context: List[Dict[str, Any]]) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        for ctx in graph_context:
            doc_id = ctx.get("document_id")
            if not doc_id:
                continue
            node_weight = float(len(ctx.get("nodes", [])) or 1)
            relationship_weight = float(len(ctx.get("relationships", [])) or 0)
            total_weight = node_weight + (relationship_weight * 0.5)
            scores[doc_id] = scores.get(doc_id, 0.0) + total_weight
        return scores

    def _compute_confidence(
        self,
        component_scores: Dict[str, float],
        weights: Dict[str, float],
        normalized_weight: float,
    ) -> float:
        weighted_sum = sum(max(component_scores.get(component, 0.0), 0.0) * weights.get(component, 0.0) for component in weights)
        normalized = weighted_sum / max(normalized_weight, 1e-6)
        return max(0.0, min(normalized, 1.0))

    def _empty_payload(self) -> Dict[str, Any]:
        return {
            "score": 0.0,
            "text_score": 0.0,
            "vector_score": 0.0,
            "graph_score": 0.0,
            "document_id": None,
            "metadata": {},
            "component_scores": {"graph": 0.0, "vector": 0.0, "text": 0.0},
            "confidence": 0.0,
        }

    def _evaluate(
        self,
        ranked: List[Dict[str, Any]],
        graph_context: List[Dict[str, Any]],
        judge: Optional[Callable[[List[Dict[str, Any]]], float]],
    ) -> tuple[float, float, float]:
        if judge is not None:
            baseline = judge(ranked)
            return baseline, 0.0, 0.0

        if not ranked:
            return 0.0, 0.0, 0.0

        graph_documents = {
            ctx.get("document_id")
            for ctx in graph_context
            if ctx.get("document_id")
        }
        hits = sum(1 for item in ranked if item.get("document_id") in graph_documents)
        coverage = hits / max(1, len(ranked))

        sources = {
            (item.get("metadata", {}).get("source"), item.get("document_id"))
            for item in ranked
            if item.get("metadata")
        }
        diversity = len({source for source, _ in sources if source}) / max(1, len(ranked))

        quality = sum(item.get("confidence", 0.0) for item in ranked) / max(1, len(ranked))
        score = (quality * 0.5) + (coverage * 0.3) + (diversity * 0.2)
        return score, coverage, diversity

    def _generate_candidate_weights(self, step: float = 0.1) -> Iterable[Dict[str, float]]:
        base = self.weights
        adjustments = [-step, 0.0, step]
        seen = set()

        for delta_graph, delta_vector, delta_text in itertools.product(adjustments, repeat=3):
            candidate = {
                "graph": max(0.0, base.get("graph", 0.0) + delta_graph),
                "vector": max(0.0, base.get("vector", 0.0) + delta_vector),
                "text": max(0.0, base.get("text", 0.0) + delta_text),
            }
            total = sum(candidate.values()) or 1.0
            normalized = {key: value / total for key, value in candidate.items()}
            key = tuple(sorted(normalized.items()))
            if key not in seen:
                seen.add(key)
                yield normalized
