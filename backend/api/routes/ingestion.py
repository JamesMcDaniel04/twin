"""FastAPI routes for document and container artifact ingestion."""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from backend.core.database import database_manager
from backend.workflows.engine import workflow_engine
from backend.workflows.ingestion import IngestionWorkflowInput

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["ingestion"])


# Enums


class IngestionSource(str, Enum):
    """Source types for ingestion."""

    UPLOAD = "upload"
    S3 = "s3"
    GCS = "gcs"
    CONTAINER = "container"
    URL = "url"


class IngestionStatus(str, Enum):
    """Status of ingestion task."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# Container Artifact Schema


class ContainerImageMetadata(BaseModel):
    """Container image metadata schema."""

    image_id: str = Field(..., description="Container image ID (SHA256 digest)")
    image_tag: str = Field(..., description="Image tag (e.g., 'v1.0.0', 'latest')")
    registry: str = Field(..., description="Container registry URL")
    repository: str = Field(..., description="Repository name")
    sbom_uri: Optional[str] = Field(None, description="URI to SBOM document (SPDX/CycloneDX)")
    sbom_format: Optional[str] = Field(None, description="SBOM format (spdx, cyclonedx)")
    created_at: Optional[str] = Field(None, description="Image creation timestamp (ISO 8601)")
    size_bytes: Optional[int] = Field(None, description="Image size in bytes")
    architecture: Optional[str] = Field(None, description="CPU architecture (amd64, arm64)")
    os: Optional[str] = Field(None, description="Operating system (linux, windows)")
    layers: Optional[List[str]] = Field(None, description="Layer digests")
    labels: Optional[Dict[str, str]] = Field(None, description="Image labels")
    env_vars: Optional[Dict[str, str]] = Field(None, description="Environment variables")
    vulnerabilities: Optional[Dict[str, object]] = Field(None, description="Vulnerability scan results")

    @field_validator("image_id")
    @classmethod
    def validate_image_id(cls, v: str) -> str:
        """Validate image ID format."""
        if not v.startswith("sha256:") or len(v) != 71:
            raise ValueError("image_id must be a valid SHA256 digest (sha256:...)")
        return v


class ContainerArtifact(BaseModel):
    """Complete container artifact schema for persistence."""

    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique artifact ID")
    metadata: ContainerImageMetadata = Field(..., description="Container image metadata")
    dockerfile: Optional[str] = Field(None, description="Dockerfile content")
    build_context: Optional[Dict[str, str]] = Field(None, description="Build context metadata")
    tags_history: Optional[List[Dict[str, str]]] = Field(None, description="Tag history")
    ingested_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# Request Models


class IngestDocumentRequest(BaseModel):
    """Request body for document ingestion."""

    source: IngestionSource = Field(..., description="Source type")
    title: Optional[str] = Field(None, description="Document title")
    mime_type: Optional[str] = Field("application/octet-stream", description="MIME type")
    tags: List[str] = Field(default_factory=list, description="Document tags")
    metadata: Dict[str, object] = Field(default_factory=dict, description="Additional metadata")

    # Source-specific fields
    document_bytes: Optional[str] = Field(None, description="Base64-encoded document content")
    s3_uri: Optional[str] = Field(None, description="S3 URI (s3://bucket/key)")
    gcs_uri: Optional[str] = Field(None, description="GCS URI (gs://bucket/blob)")
    url: Optional[str] = Field(None, description="HTTP(S) URL")

    # Container artifact specific
    container_metadata: Optional[ContainerImageMetadata] = Field(None, description="Container metadata")

    @field_validator("source")
    @classmethod
    def validate_source_fields(cls, v: IngestionSource, info) -> IngestionSource:
        """Validate that appropriate fields are set for the source type."""
        values = info.data
        if v == IngestionSource.UPLOAD and not values.get("document_bytes"):
            raise ValueError("document_bytes required for upload source")
        if v == IngestionSource.S3 and not values.get("s3_uri"):
            raise ValueError("s3_uri required for s3 source")
        if v == IngestionSource.GCS and not values.get("gcs_uri"):
            raise ValueError("gcs_uri required for gcs source")
        if v == IngestionSource.URL and not values.get("url"):
            raise ValueError("url required for url source")
        if v == IngestionSource.CONTAINER and not values.get("container_metadata"):
            raise ValueError("container_metadata required for container source")
        return v


class IngestFileRequest(BaseModel):
    """Metadata for file upload ingestion."""

    title: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, object] = Field(default_factory=dict)
    container_metadata: Optional[ContainerImageMetadata] = None


# Response Models


class IngestionTaskResponse(BaseModel):
    """Response for ingestion task submission."""

    task_id: str = Field(..., description="Ingestion task ID")
    workflow_id: str = Field(..., description="Temporal workflow ID")
    status: IngestionStatus = Field(..., description="Initial task status")
    submitted_at: str = Field(..., description="Submission timestamp")


class IngestionStatusResponse(BaseModel):
    """Response for ingestion status query."""

    task_id: str
    status: IngestionStatus
    document_id: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str
    metadata: Dict[str, object] = Field(default_factory=dict)


class IngestionListResponse(BaseModel):
    """Response for listing ingestion tasks."""

    tasks: List[IngestionStatusResponse]
    total: int
    limit: int
    offset: int


# Endpoints


@router.post("/ingest", response_model=IngestionTaskResponse, status_code=202)
async def ingest_document(request: IngestDocumentRequest) -> IngestionTaskResponse:
    """
    Ingest a document or container artifact asynchronously.

    This endpoint queues a document for ingestion through the Temporal workflow.
    Large payloads are automatically handled via Temporal's scalability.

    **Supported sources:**
    - `upload`: Base64-encoded document bytes
    - `s3`: AWS S3 URI
    - `gcs`: Google Cloud Storage URI
    - `url`: HTTP(S) URL (fetched by worker)
    - `container`: Container image metadata with SBOM

    **Container artifacts:**
    For container images, provide `container_metadata` with:
    - `image_id`: SHA256 digest
    - `image_tag`: Tag name
    - `sbom_uri`: Pointer to SBOM document (stored separately)

    The artifact is persisted to object storage and indexed in Neo4j + Pinecone/Elasticsearch.
    """
    task_id = str(uuid.uuid4())
    submitted_at = datetime.utcnow()

    await database_manager.initialize()

    # Build payload for workflow
    payload = {
        "source": request.source.value,
        "title": request.title or "Untitled",
        "mime_type": request.mime_type,
        "tags": request.tags,
        "metadata": request.metadata,
    }

    # Add source-specific fields
    if request.document_bytes:
        payload["document_bytes"] = request.document_bytes
    if request.s3_uri:
        payload["s3_uri"] = request.s3_uri
    if request.gcs_uri:
        payload["gcs_uri"] = request.gcs_uri
    if request.url:
        payload["url"] = request.url

    # Add container metadata if present
    if request.container_metadata:
        payload["container_metadata"] = request.container_metadata.model_dump()
        payload["title"] = f"{request.container_metadata.repository}:{request.container_metadata.image_tag}"
        payload["tags"].extend(["container", "artifact", request.container_metadata.registry])

    # Create task record in MongoDB
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    await mongodb["twinops"]["ingestion_tasks"].insert_one(
        {
            "task_id": task_id,
            "status": IngestionStatus.QUEUED.value,
            "payload": payload,
            "created_at": submitted_at,
            "updated_at": submitted_at,
        }
    )

    # Start Temporal workflow
    workflow_id = f"ingestion-{task_id}"
    try:
        await workflow_engine.start_workflow(
            workflow="ingestion_workflow",
            payload=IngestionWorkflowInput(task_id=task_id, payload=payload).__dict__,
            workflow_id=workflow_id,
        )
    except Exception as exc:
        logger.error(f"Failed to start workflow for task {task_id}: {exc}")
        await mongodb["twinops"]["ingestion_tasks"].update_one(
            {"task_id": task_id},
            {"$set": {"status": IngestionStatus.FAILED.value, "error": str(exc)}},
        )
        raise HTTPException(status_code=500, detail=f"Failed to start ingestion workflow: {exc}")

    logger.info(f"Ingestion task {task_id} queued with workflow {workflow_id}")

    return IngestionTaskResponse(
        task_id=task_id,
        workflow_id=workflow_id,
        status=IngestionStatus.QUEUED,
        submitted_at=submitted_at.isoformat(),
    )


@router.post("/ingest/file", response_model=IngestionTaskResponse, status_code=202)
async def ingest_file(file: UploadFile, metadata: Optional[IngestFileRequest] = None) -> IngestionTaskResponse:
    """
    Ingest a document from multipart file upload.

    This is a convenience endpoint for uploading files directly.
    The file is read into memory and processed asynchronously.

    **Note:** For large files (>100MB), prefer using S3/GCS URIs via `/ingest`.
    """
    content = await file.read()
    encoded_content = base64.b64encode(content).decode("utf-8")

    metadata = metadata or IngestFileRequest()
    title = metadata.title or file.filename or "Untitled"
    mime_type = file.content_type or "application/octet-stream"

    request = IngestDocumentRequest(
        source=IngestionSource.UPLOAD,
        title=title,
        mime_type=mime_type,
        tags=metadata.tags,
        metadata=metadata.metadata,
        document_bytes=encoded_content,
        container_metadata=metadata.container_metadata,
    )

    return await ingest_document(request)


@router.get("/ingest/{task_id}", response_model=IngestionStatusResponse)
async def get_ingestion_status(task_id: str) -> IngestionStatusResponse:
    """
    Get the status of an ingestion task.

    Returns the current status, document ID (if completed), and any error messages.
    """
    await database_manager.initialize()
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    task = await mongodb["twinops"]["ingestion_tasks"].find_one({"task_id": task_id})
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return IngestionStatusResponse(
        task_id=task["task_id"],
        status=IngestionStatus(task["status"]),
        document_id=task.get("document_id"),
        error=task.get("error"),
        created_at=task["created_at"].isoformat(),
        updated_at=task["updated_at"].isoformat(),
        metadata=task.get("payload", {}).get("metadata", {}),
    )


@router.get("/ingest", response_model=IngestionListResponse)
async def list_ingestion_tasks(
    status: Optional[IngestionStatus] = None,
    limit: int = 50,
    offset: int = 0,
) -> IngestionListResponse:
    """
    List ingestion tasks with optional status filtering.

    Supports pagination via `limit` and `offset`.
    """
    await database_manager.initialize()
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    query = {}
    if status:
        query["status"] = status.value

    collection = mongodb["twinops"]["ingestion_tasks"]
    total = await collection.count_documents(query)
    cursor = collection.find(query).sort("created_at", -1).skip(offset).limit(limit)

    tasks = []
    async for task in cursor:
        tasks.append(
            IngestionStatusResponse(
                task_id=task["task_id"],
                status=IngestionStatus(task["status"]),
                document_id=task.get("document_id"),
                error=task.get("error"),
                created_at=task["created_at"].isoformat(),
                updated_at=task["updated_at"].isoformat(),
                metadata=task.get("payload", {}).get("metadata", {}),
            )
        )

    return IngestionListResponse(tasks=tasks, total=total, limit=limit, offset=offset)


@router.delete("/ingest/{task_id}", status_code=204)
async def delete_ingestion_task(task_id: str) -> None:
    """
    Delete an ingestion task record.

    Note: This only removes the task metadata. The ingested document remains in the knowledge base.
    """
    await database_manager.initialize()
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    result = await mongodb["twinops"]["ingestion_tasks"].delete_one({"task_id": task_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
