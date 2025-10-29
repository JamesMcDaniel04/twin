"""FastAPI routes for validation and QA metrics dashboard."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from backend.core.database import database_manager
from backend.validation.harness import ValidationHarness

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/validation", tags=["validation"])


# Request/Response Models


class ValidationRunRequest(BaseModel):
    """Request to start a validation run."""

    test_suite_name: Optional[str] = Field(None, description="Name of test suite to run")
    test_case_ids: Optional[List[str]] = Field(None, description="Specific test case IDs to run")


class ValidationRunResponse(BaseModel):
    """Response from a validation run."""

    run_id: str
    status: str
    test_count: int
    executed_count: int
    timestamp: str
    aggregate_metrics: Dict[str, float]


class ValidationMetrics(BaseModel):
    """Individual test case metrics."""

    test_id: str
    precision: float
    recall: float
    f1_score: float
    ndcg: float
    mrr: float
    map_score: float
    retrieved_count: int
    relevant_count: int


class ValidationRunDetail(BaseModel):
    """Detailed validation run results."""

    run_id: str
    timestamp: str
    test_count: int
    executed_count: int
    aggregate_metrics: Dict[str, float]
    metrics: List[ValidationMetrics]
    results: List[Dict[str, Any]]


class ValidationDashboardSummary(BaseModel):
    """Summary statistics for the validation dashboard."""

    total_runs: int
    latest_run: Optional[ValidationRunDetail]
    mean_precision: float
    mean_recall: float
    mean_f1: float
    mean_ndcg: float
    trend: Dict[str, List[float]]  # Metric name -> historical values


# Endpoints


@router.post("/run", response_model=ValidationRunResponse, status_code=202)
async def run_validation(request: ValidationRunRequest) -> ValidationRunResponse:
    """
    Execute a validation run against the knowledge retrieval system.

    This endpoint runs a suite of test cases through the orchestration router
    and computes precision, recall, F1, NDCG, MRR, and MAP metrics.

    Results are persisted to MongoDB for dashboard visualization.
    """
    await database_manager.initialize()

    harness = ValidationHarness()

    # Load test cases
    # For now, we'll use a default test suite file if available
    # In production, you'd have multiple named test suites
    try:
        harness.load_test_cases_from_file("backend/validation/test_cases.json")
    except FileNotFoundError:
        logger.warning("Default test cases file not found; creating empty harness")

    if not harness.test_cases:
        raise HTTPException(status_code=400, detail="No test cases loaded")

    # Run all tests
    results = await harness.run_all_tests()

    # Persist results
    run_id = results.get("run_id", "unknown")
    await harness._persist_to_mongodb(results)

    aggregate_metrics = results.get("aggregate_metrics", {})

    return ValidationRunResponse(
        run_id=run_id,
        status="completed",
        test_count=results.get("test_count", 0),
        executed_count=results.get("executed_count", 0),
        timestamp=datetime.utcnow().isoformat(),
        aggregate_metrics=aggregate_metrics,
    )


@router.post("/test-cases/upload", status_code=201)
async def upload_test_cases(file: UploadFile) -> Dict[str, Any]:
    """
    Upload a JSON file containing test cases.

    Expected format:
    ```json
    {
        "test_cases": [
            {
                "test_id": "test-1",
                "query": "What containers are vulnerable?",
                "expected_documents": ["doc-1", "doc-2"],
                "relevance_scores": {"doc-1": 1.0, "doc-2": 0.8},
                "category": "container"
            }
        ]
    }
    ```
    """
    import json
    import tempfile

    # Save uploaded file temporarily
    content = await file.read()
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".json") as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    # Validate JSON format
    try:
        with open(tmp_path) as f:
            data = json.load(f)
            test_cases = data.get("test_cases", [])

        if not test_cases:
            raise HTTPException(status_code=400, detail="No test cases found in file")

        # Persist to MongoDB
        await database_manager.initialize()
        mongodb = database_manager.mongodb
        if mongodb is None:
            raise HTTPException(status_code=503, detail="Database unavailable")

        await mongodb["twinops"]["test_suites"].insert_one(
            {
                "name": file.filename or "unnamed",
                "uploaded_at": datetime.utcnow(),
                "test_cases": test_cases,
                "test_count": len(test_cases),
            }
        )

        return {
            "message": f"Uploaded {len(test_cases)} test cases",
            "test_count": len(test_cases),
            "filename": file.filename,
        }

    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON format: {exc}")


@router.get("/runs", response_model=List[ValidationRunDetail])
async def list_validation_runs(limit: int = 50, offset: int = 0) -> List[ValidationRunDetail]:
    """
    List historical validation runs with metrics.

    Supports pagination via `limit` and `offset`.
    """
    await database_manager.initialize()
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    cursor = mongodb["twinops"]["validation_runs"].find().sort("timestamp", -1).skip(offset).limit(limit)

    runs = []
    async for run in cursor:
        runs.append(
            ValidationRunDetail(
                run_id=run.get("run_id", "unknown"),
                timestamp=run["timestamp"].isoformat(),
                test_count=run.get("test_count", 0),
                executed_count=run.get("test_count", 0),
                aggregate_metrics=run.get("aggregate_metrics", {}),
                metrics=[ValidationMetrics(**m) for m in run.get("metrics", [])],
                results=run.get("results", []),
            )
        )

    return runs


@router.get("/runs/{run_id}", response_model=ValidationRunDetail)
async def get_validation_run(run_id: str) -> ValidationRunDetail:
    """
    Get detailed results for a specific validation run.
    """
    await database_manager.initialize()
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    run = await mongodb["twinops"]["validation_runs"].find_one({"run_id": run_id})
    if not run:
        raise HTTPException(status_code=404, detail=f"Validation run {run_id} not found")

    return ValidationRunDetail(
        run_id=run.get("run_id", run_id),
        timestamp=run["timestamp"].isoformat(),
        test_count=run.get("test_count", 0),
        executed_count=run.get("test_count", 0),
        aggregate_metrics=run.get("aggregate_metrics", {}),
        metrics=[ValidationMetrics(**m) for m in run.get("metrics", [])],
        results=run.get("results", []),
    )


@router.get("/dashboard", response_model=ValidationDashboardSummary)
async def get_dashboard_summary() -> ValidationDashboardSummary:
    """
    Get summary statistics for the QA dashboard.

    Returns aggregate metrics, trends, and latest run results.
    """
    await database_manager.initialize()
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    # Get total run count
    total_runs = await mongodb["twinops"]["validation_runs"].count_documents({})

    # Get latest run
    latest_run_doc = await mongodb["twinops"]["validation_runs"].find_one(sort=[("timestamp", -1)])
    latest_run = None
    if latest_run_doc:
        latest_run = ValidationRunDetail(
            run_id=latest_run_doc.get("run_id", "unknown"),
            timestamp=latest_run_doc["timestamp"].isoformat(),
            test_count=latest_run_doc.get("test_count", 0),
            executed_count=latest_run_doc.get("test_count", 0),
            aggregate_metrics=latest_run_doc.get("aggregate_metrics", {}),
            metrics=[ValidationMetrics(**m) for m in latest_run_doc.get("metrics", [])],
            results=latest_run_doc.get("results", []),
        )

    # Compute mean metrics across last 10 runs
    cursor = mongodb["twinops"]["validation_runs"].find().sort("timestamp", -1).limit(10)
    runs = []
    async for run in cursor:
        runs.append(run)

    mean_precision = 0.0
    mean_recall = 0.0
    mean_f1 = 0.0
    mean_ndcg = 0.0

    if runs:
        mean_precision = sum(r.get("aggregate_metrics", {}).get("mean_precision", 0.0) for r in runs) / len(runs)
        mean_recall = sum(r.get("aggregate_metrics", {}).get("mean_recall", 0.0) for r in runs) / len(runs)
        mean_f1 = sum(r.get("aggregate_metrics", {}).get("mean_f1", 0.0) for r in runs) / len(runs)
        mean_ndcg = sum(r.get("aggregate_metrics", {}).get("mean_ndcg", 0.0) for r in runs) / len(runs)

    # Build trend data (last 10 runs)
    trend = {
        "precision": [r.get("aggregate_metrics", {}).get("mean_precision", 0.0) for r in reversed(runs)],
        "recall": [r.get("aggregate_metrics", {}).get("mean_recall", 0.0) for r in reversed(runs)],
        "f1": [r.get("aggregate_metrics", {}).get("mean_f1", 0.0) for r in reversed(runs)],
        "ndcg": [r.get("aggregate_metrics", {}).get("mean_ndcg", 0.0) for r in reversed(runs)],
    }

    return ValidationDashboardSummary(
        total_runs=total_runs,
        latest_run=latest_run,
        mean_precision=mean_precision,
        mean_recall=mean_recall,
        mean_f1=mean_f1,
        mean_ndcg=mean_ndcg,
        trend=trend,
    )


@router.delete("/runs/{run_id}", status_code=204)
async def delete_validation_run(run_id: str) -> None:
    """
    Delete a validation run.
    """
    await database_manager.initialize()
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    result = await mongodb["twinops"]["validation_runs"].delete_one({"run_id": run_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Validation run {run_id} not found")
