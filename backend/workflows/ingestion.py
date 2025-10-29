"""Temporal workflow and activities for document ingestion."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from backend.core.database import database_manager
from backend.knowledge.ingestion.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)


@dataclass
class IngestionWorkflowInput:
    """Input for the ingestion workflow."""

    task_id: str
    payload: Dict[str, object]


@dataclass
class IngestionResult:
    """Result of the ingestion workflow."""

    document_id: str
    status: str
    error: Optional[str] = None


# Activities


@activity.defn(name="fetch_document_content")
async def fetch_document_content(payload: Dict[str, object]) -> bytes:
    """
    Activity to fetch document content from various sources.

    Supports:
    - Base64-encoded bytes
    - S3 URIs
    - GCS URIs
    - HTTP(S) URLs
    """
    activity.logger.info("Fetching document content")

    if "document_bytes" in payload:
        return base64.b64decode(payload["document_bytes"])

    if "s3_uri" in payload:
        import boto3

        s3 = boto3.client("s3")
        bucket, key = _parse_s3_uri(payload["s3_uri"])
        response = s3.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()
        activity.logger.info(f"Fetched {len(content)} bytes from S3: {payload['s3_uri']}")
        return content

    if "gcs_uri" in payload:
        from google.cloud import storage

        client = storage.Client()
        bucket, blob = _parse_gcs_uri(payload["gcs_uri"])
        content = client.bucket(bucket).blob(blob).download_as_bytes()
        activity.logger.info(f"Fetched {len(content)} bytes from GCS: {payload['gcs_uri']}")
        return content

    if "url" in payload:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(payload["url"]) as response:
                response.raise_for_status()
                content = await response.read()
                activity.logger.info(f"Fetched {len(content)} bytes from URL: {payload['url']}")
                return content

    raise ValueError("No valid content source in payload")


@activity.defn(name="ingest_document_to_knowledge_base")
async def ingest_document_to_knowledge_base(
    task_id: str,
    content: bytes,
    payload: Dict[str, object],
) -> str:
    """
    Activity to process document through the ingestion pipeline.

    Args:
        task_id: Task identifier
        content: Document content bytes
        payload: Ingestion payload with metadata

    Returns:
        Document ID
    """
    activity.logger.info(f"Processing document ingestion for task {task_id}")

    # Ensure database is initialized
    await database_manager.initialize()

    # Prepare metadata
    metadata = payload.get("metadata", {})
    metadata["source_type"] = payload["source"]

    container_metadata = payload.get("container_metadata")
    if container_metadata:
        metadata.update(container_metadata)
        activity.logger.info(f"Processing container artifact: {container_metadata.get('image_id')}")

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

    activity.logger.info(f"Document ingestion completed: {document_id}")
    return document_id


@activity.defn(name="update_ingestion_status")
async def update_ingestion_status(
    task_id: str,
    status: str,
    document_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """
    Activity to update ingestion task status in MongoDB.

    Args:
        task_id: Task identifier
        status: New status (queued, processing, completed, failed)
        document_id: Document ID (if completed)
        error: Error message (if failed)
    """
    activity.logger.info(f"Updating task {task_id} status to {status}")

    await database_manager.initialize()

    mongodb = database_manager.mongodb
    if mongodb is None:
        raise RuntimeError("MongoDB not available")

    update_fields = {
        "status": status,
        "updated_at": datetime.utcnow(),
    }

    if document_id:
        update_fields["document_id"] = document_id
    if error:
        update_fields["error"] = error

    await mongodb["twinops"]["ingestion_tasks"].update_one(
        {"task_id": task_id},
        {"$set": update_fields},
    )

    activity.logger.info(f"Task {task_id} updated successfully")


# Workflow


@workflow.defn(name="ingestion_workflow")
class IngestionWorkflow:
    """
    Temporal workflow for document and container artifact ingestion.

    This workflow orchestrates:
    1. Fetching document content from source
    2. Processing through ingestion pipeline
    3. Updating task status
    """

    @workflow.run
    async def run(self, input_data: IngestionWorkflowInput) -> IngestionResult:
        """Execute the ingestion workflow."""
        task_id = input_data.task_id
        payload = input_data.payload

        workflow.logger.info(f"Starting ingestion workflow for task {task_id}")

        # Define retry policy for activities
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=60),
            maximum_attempts=3,
            backoff_coefficient=2.0,
        )

        try:
            # Update status to processing
            await workflow.execute_activity(
                update_ingestion_status,
                args=[task_id, "processing"],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry_policy,
            )

            # Fetch document content
            content = await workflow.execute_activity(
                fetch_document_content,
                args=[payload],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Fetched {len(content)} bytes for task {task_id}")

            # Process ingestion
            document_id = await workflow.execute_activity(
                ingest_document_to_knowledge_base,
                args=[task_id, content, payload],
                start_to_close_timeout=timedelta(minutes=30),
                retry_policy=retry_policy,
            )

            workflow.logger.info(f"Ingestion completed for task {task_id}: document {document_id}")

            # Update status to completed
            await workflow.execute_activity(
                update_ingestion_status,
                args=[task_id, "completed", document_id],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry_policy,
            )

            return IngestionResult(
                document_id=document_id,
                status="completed",
            )

        except Exception as exc:
            workflow.logger.error(f"Ingestion workflow failed for task {task_id}: {exc}")

            # Update status to failed
            try:
                await workflow.execute_activity(
                    update_ingestion_status,
                    args=[task_id, "failed", None, str(exc)],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry_policy,
                )
            except Exception as update_exc:
                workflow.logger.error(f"Failed to update task status: {update_exc}")

            return IngestionResult(
                document_id="",
                status="failed",
                error=str(exc),
            )


# Helper functions


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
