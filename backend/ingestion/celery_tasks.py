"""Celery tasks for background document ingestion."""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Dict

from celery import Celery, Task
from celery.result import AsyncResult

from backend.core.config import settings
from backend.core.database import database_manager
from backend.knowledge.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)

# Initialize Celery app
celery_app = Celery(
    "twinops_ingestion",
    broker=str(settings.REDIS_URL),
    backend=str(settings.REDIS_URL),
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    task_soft_time_limit=3300,  # 55 minutes soft limit
    worker_prefetch_multiplier=1,  # Fetch one task at a time for heavy workloads
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks to prevent memory leaks
)


class DatabaseTask(Task):
    """Base task that ensures database connections are initialized."""

    _db_initialized = False

    def before_start(self, task_id, args, kwargs):
        """Initialize database connections before task execution."""
        if not self._db_initialized:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(database_manager.initialize())
            else:
                loop.run_until_complete(database_manager.initialize())
            self._db_initialized = True


@celery_app.task(base=DatabaseTask, bind=True, name="twinops.ingestion.ingest_document")
def ingest_document_task(self, task_id: str, payload: Dict[str, object]) -> Dict[str, object]:
    """
    Celery task for document ingestion.

    Args:
        task_id: Unique task identifier
        payload: Ingestion payload matching IngestDocumentPayload schema

    Returns:
        Dictionary with document_id and status
    """
    import asyncio

    loop = asyncio.get_event_loop()

    async def _async_ingest():
        mongodb = database_manager.mongodb
        if mongodb is None:
            raise RuntimeError("MongoDB not available")

        try:
            # Update status to processing
            await mongodb["twinops"]["ingestion_tasks"].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "status": "processing",
                        "celery_task_id": self.request.id,
                        "updated_at": datetime.utcnow(),
                    }
                },
            )

            # Fetch document content
            content = await _fetch_content(payload)

            # Prepare metadata
            metadata = payload.get("metadata", {})
            metadata["source_type"] = payload["source"]

            container_metadata = payload.get("container_metadata")
            if container_metadata:
                metadata.update(container_metadata)

            # Call ingestion pipeline
            pipeline = IngestionPipeline()
            document_id = await pipeline.ingest_document(
                source=payload["source"],
                content=content,
                metadata={
                    "title": payload.get("title", "Untitled"),
                    "mime_type": payload.get("mime_type", "application/octet-stream"),
                    "tags": payload.get("tags", []),
                    **metadata,
                },
            )

            # Update task status to completed
            await mongodb["twinops"]["ingestion_tasks"].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "status": "completed",
                        "document_id": document_id,
                        "updated_at": datetime.utcnow(),
                    }
                },
            )

            logger.info(f"Celery task {self.request.id} completed ingestion for document {document_id}")

            return {"document_id": document_id, "status": "completed"}

        except Exception as exc:
            logger.error(f"Celery task {self.request.id} failed: {exc}", exc_info=True)

            # Update task status to failed
            await mongodb["twinops"]["ingestion_tasks"].update_one(
                {"task_id": task_id},
                {
                    "$set": {
                        "status": "failed",
                        "error": str(exc),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )

            raise

    return loop.run_until_complete(_async_ingest())


async def _fetch_content(payload: Dict[str, object]) -> bytes:
    """Fetch document content from payload."""
    if "document_bytes" in payload:
        return base64.b64decode(payload["document_bytes"])

    if "s3_uri" in payload:
        import boto3

        s3 = boto3.client("s3")
        bucket, key = _parse_s3_uri(payload["s3_uri"])
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    if "gcs_uri" in payload:
        from google.cloud import storage

        client = storage.Client()
        bucket, blob = _parse_gcs_uri(payload["gcs_uri"])
        return client.bucket(bucket).blob(blob).download_as_bytes()

    raise ValueError("No valid content source in payload")


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


def get_task_status(celery_task_id: str) -> Dict[str, object]:
    """
    Get Celery task status via result backend.

    Args:
        celery_task_id: Celery task ID

    Returns:
        Dictionary with task state and result
    """
    result = AsyncResult(celery_task_id, app=celery_app)
    return {
        "task_id": celery_task_id,
        "state": result.state,
        "result": result.result if result.ready() else None,
        "info": result.info,
    }
