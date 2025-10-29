"""FastAPI ingestion API for document and container artifact ingestion."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl, validator

from backend.core.config import settings
from backend.core.database import database_manager
from backend.knowledge.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)

router = APIRouter()


class SourceType(str, Enum):
    """Document source types."""

    CONTAINER_IMAGE = "container_image"
    SBOM = "sbom"
    DOCUMENT = "document"
    CONFLUENCE = "confluence"
    GITHUB = "github"
    JIRA = "jira"
    SLACK = "slack"


class IngestionStatus(str, Enum):
    """Ingestion task status."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ContainerMetadata(BaseModel):
    """Container-specific metadata schema."""

    # Required fields
    image_id: str = Field(..., description="Container image SHA digest")
    tag: str = Field(..., description="Image tag (e.g., v1.2.3 or latest)")
    repository: str = Field(..., description="Container repository (e.g., myorg/myapp)")
    sbom_uri: Optional[str] = Field(None, description="URI to SBOM artifact in object storage")
    artifact_uri: str = Field(..., description="URI to container artifact in registry or object storage")
    ingested_at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="Ingestion timestamp")
    version: str = Field(..., description="Semantic version or build number")

    # Optional fields
    base_image: Optional[str] = Field(None, description="Base image (e.g., alpine:3.18)")
    runtime: Optional[str] = Field(None, description="Runtime environment (e.g., python:3.11)")
    vulnerabilities: Optional[List[Dict[str, object]]] = Field(
        default_factory=list, description="Known vulnerabilities from scanning"
    )
    owner_team: Optional[str] = Field(None, description="Owning team or service name")
    labels: Optional[Dict[str, str]] = Field(default_factory=dict, description="Container labels")
    build_info: Optional[Dict[str, object]] = Field(default_factory=dict, description="Build metadata")

    @validator("image_id")
    def validate_image_id(cls, v: str) -> str:
        """Validate image_id is a valid SHA256 digest."""
        if not v.startswith("sha256:"):
            if len(v) == 64:  # Plain SHA256 hex
                return f"sha256:{v}"
            raise ValueError("image_id must be a SHA256 digest (sha256:... or 64-char hex)")
        return v


class IngestDocumentPayload(BaseModel):
    """Request payload for document ingestion."""

    source: SourceType = Field(..., description="Document source type")
    document_bytes: Optional[str] = Field(None, description="Base64-encoded document bytes")
    s3_uri: Optional[str] = Field(None, description="S3 URI for large documents")
    gcs_uri: Optional[str] = Field(None, description="GCS URI for large documents")

    # General metadata
    title: Optional[str] = Field(None, description="Document title")
    mime_type: Optional[str] = Field("application/octet-stream", description="MIME type")
    tags: Optional[List[str]] = Field(default_factory=list, description="Document tags")
    metadata: Optional[Dict[str, object]] = Field(default_factory=dict, description="Additional metadata")

    # Container-specific metadata
    container_metadata: Optional[ContainerMetadata] = Field(None, description="Container artifact metadata")

    @validator("document_bytes", "s3_uri", "gcs_uri", always=True)
    def validate_content_source(cls, v, values, field) -> Optional[str]:
        """Ensure exactly one content source is provided."""
        sources = [values.get("document_bytes"), values.get("s3_uri"), values.get("gcs_uri")]
        provided = sum(1 for src in sources if src is not None)

        if provided == 0:
            raise ValueError("Must provide one of: document_bytes, s3_uri, or gcs_uri")
        if provided > 1:
            raise ValueError("Provide only one content source: document_bytes, s3_uri, or gcs_uri")
        return v

    @validator("container_metadata")
    def validate_container_source(cls, v, values) -> Optional[ContainerMetadata]:
        """Validate container metadata is provided for container sources."""
        source = values.get("source")
        if source in [SourceType.CONTAINER_IMAGE, SourceType.SBOM]:
            if v is None:
                raise ValueError(f"container_metadata is required for source type {source}")
        return v


class IngestResponse(BaseModel):
    """Response for ingestion request."""

    task_id: str = Field(..., description="Task or workflow ID for tracking")
    status: IngestionStatus = Field(..., description="Current ingestion status")
    message: str = Field(..., description="Human-readable status message")
    document_id: Optional[str] = Field(None, description="Document ID (if immediately available)")


class IngestStatusResponse(BaseModel):
    """Response for ingestion status query."""

    task_id: str = Field(..., description="Task or workflow ID")
    status: IngestionStatus = Field(..., description="Current status")
    document_id: Optional[str] = Field(None, description="Document ID (if completed)")
    error: Optional[str] = Field(None, description="Error message (if failed)")
    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    metadata: Optional[Dict[str, object]] = Field(default_factory=dict, description="Task metadata")


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_document(payload: IngestDocumentPayload, background_tasks: BackgroundTasks) -> IngestResponse:
    """
    Ingest a document or container artifact for knowledge base indexing.

    This endpoint accepts documents via:
    - Direct base64-encoded bytes (for small documents)
    - S3/GCS URIs (for large documents)

    For container artifacts (images/SBOMs), include container_metadata with
    required fields like image_id, tag, repository, etc.

    Returns 202 Accepted with a task_id for tracking ingestion progress.
    Use GET /api/ingest/{task_id} to poll status.
    """
    task_id = str(uuid.uuid4())

    # Store task record in MongoDB
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    task_record = {
        "task_id": task_id,
        "status": IngestionStatus.QUEUED.value,
        "payload": payload.dict(exclude_none=True),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    await mongodb["twinops"]["ingestion_tasks"].insert_one(task_record)

    # Check if we should use Celery or Temporal based on configuration
    use_temporal = settings.TEMPORAL_HOST and payload.source in [
        SourceType.CONTAINER_IMAGE,
        SourceType.SBOM,
    ]

    if use_temporal:
        # Defer to Temporal workflow for container artifacts
        from backend.workflows.engine import workflow_engine

        try:
            workflow_id = await workflow_engine.start_workflow(
                "ingestion",
                {
                    "task_id": task_id,
                    "payload": payload.dict(exclude_none=True),
                },
            )
            logger.info(f"Started Temporal workflow {workflow_id} for task {task_id}")
        except Exception as exc:
            logger.error(f"Failed to start Temporal workflow: {exc}")
            # Fall back to background task
            background_tasks.add_task(_process_ingestion_task, task_id, payload)
    else:
        # Use FastAPI background tasks for lightweight ingestion
        # In production, this should be replaced with Celery
        background_tasks.add_task(_process_ingestion_task, task_id, payload)

    return IngestResponse(
        task_id=task_id,
        status=IngestionStatus.QUEUED,
        message="Ingestion task queued for processing",
    )


@router.get("/ingest/{task_id}", response_model=IngestStatusResponse)
async def get_ingestion_status(task_id: str) -> IngestStatusResponse:
    """
    Get the status of an ingestion task.

    Returns the current status, document_id (if completed), and any error details.
    """
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    task = await mongodb["twinops"]["ingestion_tasks"].find_one({"task_id": task_id})

    if task is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return IngestStatusResponse(
        task_id=task["task_id"],
        status=IngestionStatus(task["status"]),
        document_id=task.get("document_id"),
        error=task.get("error"),
        created_at=task["created_at"],
        updated_at=task["updated_at"],
        metadata=task.get("metadata", {}),
    )


async def _process_ingestion_task(task_id: str, payload: IngestDocumentPayload) -> None:
    """
    Background task to process document ingestion.

    This is a lightweight implementation. For production use with large documents,
    replace this with a Celery task or Temporal workflow.
    """
    mongodb = database_manager.mongodb
    if mongodb is None:
        logger.error("MongoDB unavailable; cannot process ingestion task")
        return

    try:
        # Update status to processing
        await mongodb["twinops"]["ingestion_tasks"].update_one(
            {"task_id": task_id},
            {"$set": {"status": IngestionStatus.PROCESSING.value, "updated_at": datetime.utcnow()}},
        )

        # Fetch document content
        content = await _fetch_document_content(payload)

        # Prepare metadata
        metadata = payload.metadata or {}
        metadata["source_type"] = payload.source.value

        if payload.container_metadata:
            # Merge container metadata into main metadata
            metadata.update(payload.container_metadata.dict(exclude_none=True))

        # Call ingestion pipeline
        pipeline = IngestionPipeline()
        document_id = await pipeline.ingest_document(
            source=payload.source.value,
            content=content,
            metadata={
                "title": payload.title or "Untitled",
                "mime_type": payload.mime_type,
                "tags": payload.tags,
                **metadata,
            },
        )

        # Update task status to completed
        await mongodb["twinops"]["ingestion_tasks"].update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "status": IngestionStatus.COMPLETED.value,
                    "document_id": document_id,
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        logger.info(f"Ingestion task {task_id} completed successfully (document_id: {document_id})")

    except Exception as exc:
        logger.error(f"Ingestion task {task_id} failed: {exc}", exc_info=True)

        # Update task status to failed
        await mongodb["twinops"]["ingestion_tasks"].update_one(
            {"task_id": task_id},
            {
                "$set": {
                    "status": IngestionStatus.FAILED.value,
                    "error": str(exc),
                    "updated_at": datetime.utcnow(),
                }
            },
        )


async def _fetch_document_content(payload: IngestDocumentPayload) -> bytes:
    """Fetch document content from the specified source."""
    import base64

    if payload.document_bytes:
        return base64.b64decode(payload.document_bytes)

    if payload.s3_uri:
        # Fetch from S3
        import boto3

        s3 = boto3.client("s3")
        bucket, key = _parse_s3_uri(payload.s3_uri)
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    if payload.gcs_uri:
        # Fetch from GCS
        from google.cloud import storage

        client = storage.Client()
        bucket, blob = _parse_gcs_uri(payload.gcs_uri)
        return client.bucket(bucket).blob(blob).download_as_bytes()

    raise ValueError("No valid content source provided")


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    """Parse S3 URI into bucket and key."""
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {uri}")
    parts = uri[5:].split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid S3 URI format: {uri}")
    return parts[0], parts[1]


def _parse_gcs_uri(uri: str) -> tuple[str, str]:
    """Parse GCS URI into bucket and blob."""
    if not uri.startswith("gs://"):
        raise ValueError(f"Invalid GCS URI: {uri}")
    parts = uri[5:].split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid GCS URI format: {uri}")
    return parts[0], parts[1]
