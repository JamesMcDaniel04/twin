"""Validation harness for testing precision and recall of the knowledge retrieval system."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.database import database_manager
from backend.orchestration.router import OrchestrationRouter

logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """A test case with query, expected documents, and relevance judgments."""

    test_id: str
    query: str
    expected_documents: List[str]  # Document IDs expected to be relevant
    relevance_scores: Dict[str, float] = field(default_factory=dict)  # Document ID -> relevance (0-1)
    category: str = "general"  # Test category (e.g., "container", "incident", "general")
    description: Optional[str] = None


@dataclass
class RetrievalResult:
    """Result from a single retrieval."""

    test_id: str
    query: str
    retrieved_documents: List[str]  # Retrieved document IDs in rank order
    scores: Dict[str, float]  # Document ID -> retrieval score
    execution_time_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MetricsResult:
    """Computed metrics for a test case."""

    test_id: str
    precision: float
    recall: float
    f1_score: float
    ndcg: float  # Normalized Discounted Cumulative Gain
    mrr: float  # Mean Reciprocal Rank
    map_score: float  # Mean Average Precision
    retrieved_count: int
    relevant_count: int
    true_positives: int
    false_positives: int
    false_negatives: int


class ValidationHarness:
    """Harness for running validation tests against the knowledge retrieval system."""

    def __init__(self, router: Optional[OrchestrationRouter] = None) -> None:
        self.router = router or OrchestrationRouter()
        self.test_cases: List[TestCase] = []

    def load_test_cases_from_file(self, file_path: str) -> None:
        """
        Load test cases from a JSON file.

        Expected format:
        {
            "test_cases": [
                {
                    "test_id": "test-1",
                    "query": "What containers are vulnerable to CVE-2024-1234?",
                    "expected_documents": ["doc-1", "doc-2"],
                    "relevance_scores": {"doc-1": 1.0, "doc-2": 0.8},
                    "category": "container",
                    "description": "Test vulnerability search"
                }
            ]
        }
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Test cases file not found: {file_path}")

        with open(path) as f:
            data = json.load(f)

        for case_data in data.get("test_cases", []):
            test_case = TestCase(
                test_id=case_data["test_id"],
                query=case_data["query"],
                expected_documents=case_data.get("expected_documents", []),
                relevance_scores=case_data.get("relevance_scores", {}),
                category=case_data.get("category", "general"),
                description=case_data.get("description"),
            )
            self.test_cases.append(test_case)

        logger.info(f"Loaded {len(self.test_cases)} test cases from {file_path}")

    def add_test_case(self, test_case: TestCase) -> None:
        """Add a single test case programmatically."""
        self.test_cases.append(test_case)

    async def run_test_case(self, test_case: TestCase) -> RetrievalResult:
        """
        Run a single test case through the orchestration router.

        Args:
            test_case: Test case to run

        Returns:
            RetrievalResult with retrieved documents and scores
        """
        session_id = str(uuid.uuid4())
        user_id = "validation-harness"

        start_time = datetime.utcnow()
        response = await self.router.route(
            session_id=session_id,
            user_id=user_id,
            text=test_case.query,
        )
        end_time = datetime.utcnow()

        execution_time_ms = (end_time - start_time).total_seconds() * 1000

        # Extract document IDs and scores from response
        retrieved_documents = []
        scores = {}

        # Response format from router includes 'documents' and 'citations'
        for doc in response.get("documents", []):
            doc_id = doc.get("document_id") or doc.get("id")
            if doc_id:
                retrieved_documents.append(doc_id)
                scores[doc_id] = doc.get("score", 0.0)

        return RetrievalResult(
            test_id=test_case.test_id,
            query=test_case.query,
            retrieved_documents=retrieved_documents,
            scores=scores,
            execution_time_ms=execution_time_ms,
            metadata=response,
        )

    @staticmethod
    def compute_metrics(test_case: TestCase, result: RetrievalResult) -> MetricsResult:
        """
        Compute precision, recall, F1, NDCG, MRR, and MAP for a retrieval result.

        Args:
            test_case: Original test case with expected documents
            result: Retrieval result

        Returns:
            MetricsResult with computed metrics
        """
        expected_set = set(test_case.expected_documents)
        retrieved_set = set(result.retrieved_documents)

        # Basic metrics
        true_positives = len(expected_set & retrieved_set)
        false_positives = len(retrieved_set - expected_set)
        false_negatives = len(expected_set - retrieved_set)

        precision = true_positives / len(retrieved_set) if retrieved_set else 0.0
        recall = true_positives / len(expected_set) if expected_set else 0.0
        f1_score = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

        # NDCG (Normalized Discounted Cumulative Gain)
        ndcg = ValidationHarness._compute_ndcg(test_case, result)

        # MRR (Mean Reciprocal Rank)
        mrr = ValidationHarness._compute_mrr(test_case, result)

        # MAP (Mean Average Precision)
        map_score = ValidationHarness._compute_map(test_case, result)

        return MetricsResult(
            test_id=test_case.test_id,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            ndcg=ndcg,
            mrr=mrr,
            map_score=map_score,
            retrieved_count=len(retrieved_set),
            relevant_count=len(expected_set),
            true_positives=true_positives,
            false_positives=false_positives,
            false_negatives=false_negatives,
        )

    @staticmethod
    def _compute_ndcg(test_case: TestCase, result: RetrievalResult, k: int = 10) -> float:
        """Compute Normalized Discounted Cumulative Gain @ k."""
        relevance_scores = test_case.relevance_scores
        if not relevance_scores:
            # Binary relevance: 1 if in expected, 0 otherwise
            relevance_scores = {doc_id: 1.0 for doc_id in test_case.expected_documents}

        # DCG: sum of (relevance / log2(rank + 1))
        dcg = 0.0
        for rank, doc_id in enumerate(result.retrieved_documents[:k], start=1):
            relevance = relevance_scores.get(doc_id, 0.0)
            dcg += relevance / (rank + 1).bit_length()  # log2(rank + 1)

        # Ideal DCG: sort by relevance descending
        ideal_relevances = sorted(relevance_scores.values(), reverse=True)
        idcg = sum(rel / (rank + 1).bit_length() for rank, rel in enumerate(ideal_relevances[:k], start=1))

        return dcg / idcg if idcg > 0 else 0.0

    @staticmethod
    def _compute_mrr(test_case: TestCase, result: RetrievalResult) -> float:
        """Compute Mean Reciprocal Rank."""
        expected_set = set(test_case.expected_documents)
        for rank, doc_id in enumerate(result.retrieved_documents, start=1):
            if doc_id in expected_set:
                return 1.0 / rank
        return 0.0

    @staticmethod
    def _compute_map(test_case: TestCase, result: RetrievalResult) -> float:
        """Compute Mean Average Precision."""
        expected_set = set(test_case.expected_documents)
        if not expected_set:
            return 0.0

        precisions = []
        relevant_count = 0

        for rank, doc_id in enumerate(result.retrieved_documents, start=1):
            if doc_id in expected_set:
                relevant_count += 1
                precision_at_k = relevant_count / rank
                precisions.append(precision_at_k)

        return sum(precisions) / len(expected_set) if precisions else 0.0

    async def run_all_tests(self) -> Dict[str, Any]:
        """
        Run all test cases and compute aggregate metrics.

        Returns:
            Dictionary with results and aggregate metrics
        """
        if not self.test_cases:
            logger.warning("No test cases loaded")
            return {}

        await database_manager.initialize()

        results = []
        metrics = []

        for test_case in self.test_cases:
            logger.info(f"Running test case: {test_case.test_id} - {test_case.query}")
            try:
                result = await self.run_test_case(test_case)
                metric = self.compute_metrics(test_case, result)
                results.append(result)
                metrics.append(metric)
                logger.info(
                    f"Test {test_case.test_id}: P={metric.precision:.3f}, "
                    f"R={metric.recall:.3f}, F1={metric.f1_score:.3f}, "
                    f"NDCG={metric.ndcg:.3f}, MRR={metric.mrr:.3f}"
                )
            except Exception as exc:
                logger.error(f"Test case {test_case.test_id} failed: {exc}", exc_info=True)

        # Compute aggregate metrics
        aggregate = ValidationHarness._compute_aggregate_metrics(metrics)

        return {
            "test_count": len(self.test_cases),
            "executed_count": len(results),
            "aggregate_metrics": aggregate,
            "metrics": [
                {
                    "test_id": m.test_id,
                    "precision": m.precision,
                    "recall": m.recall,
                    "f1_score": m.f1_score,
                    "ndcg": m.ndcg,
                    "mrr": m.mrr,
                    "map_score": m.map_score,
                    "retrieved_count": m.retrieved_count,
                    "relevant_count": m.relevant_count,
                }
                for m in metrics
            ],
            "results": [
                {
                    "test_id": r.test_id,
                    "query": r.query,
                    "retrieved_documents": r.retrieved_documents,
                    "execution_time_ms": r.execution_time_ms,
                }
                for r in results
            ],
        }

    @staticmethod
    def _compute_aggregate_metrics(metrics: List[MetricsResult]) -> Dict[str, float]:
        """Compute aggregate metrics across all test cases."""
        if not metrics:
            return {}

        return {
            "mean_precision": sum(m.precision for m in metrics) / len(metrics),
            "mean_recall": sum(m.recall for m in metrics) / len(metrics),
            "mean_f1": sum(m.f1_score for m in metrics) / len(metrics),
            "mean_ndcg": sum(m.ndcg for m in metrics) / len(metrics),
            "mean_mrr": sum(m.mrr for m in metrics) / len(metrics),
            "mean_map": sum(m.map_score for m in metrics) / len(metrics),
            "total_retrieved": sum(m.retrieved_count for m in metrics),
            "total_relevant": sum(m.relevant_count for m in metrics),
            "total_true_positives": sum(m.true_positives for m in metrics),
            "total_false_positives": sum(m.false_positives for m in metrics),
            "total_false_negatives": sum(m.false_negatives for m in metrics),
        }

    async def save_results(self, results: Dict[str, Any], output_path: str) -> None:
        """
        Save validation results to a JSON file.

        Args:
            results: Results from run_all_tests()
            output_path: Path to output file
        """
        # Add timestamp
        results["timestamp"] = datetime.utcnow().isoformat()

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(results, f, indent=2)

        logger.info(f"Validation results saved to {output_path}")

        # Also persist to MongoDB for dashboard
        await self._persist_to_mongodb(results)

    async def _persist_to_mongodb(self, results: Dict[str, Any]) -> None:
        """Persist validation results to MongoDB for dashboard access."""
        mongodb = database_manager.mongodb
        if mongodb is None:
            logger.warning("MongoDB unavailable; skipping result persistence")
            return

        await mongodb["twinops"]["validation_runs"].insert_one(
            {
                "run_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow(),
                "test_count": results.get("test_count"),
                "aggregate_metrics": results.get("aggregate_metrics"),
                "metrics": results.get("metrics"),
                "results": results.get("results"),
            }
        )
        logger.info("Validation results persisted to MongoDB")


# Example test cases for container artifacts
CONTAINER_TEST_CASES = [
    {
        "test_id": "container-vuln-1",
        "query": "Which containers have critical vulnerabilities?",
        "expected_documents": [],  # To be filled with actual document IDs
        "category": "container",
        "description": "Test retrieval of containers with critical vulnerabilities",
    },
    {
        "test_id": "container-sbom-1",
        "query": "Show me the SBOM for the backend API container",
        "expected_documents": [],
        "category": "container",
        "description": "Test SBOM document retrieval",
    },
    {
        "test_id": "container-registry-1",
        "query": "List all containers from the production registry",
        "expected_documents": [],
        "category": "container",
        "description": "Test registry filtering",
    },
]
