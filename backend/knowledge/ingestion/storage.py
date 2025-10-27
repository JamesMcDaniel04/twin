"""Object storage abstraction for raw document persistence."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from backend.core.config import settings

try:  # Optional dependency
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover - optional
    boto3 = None
    ClientError = BotoCoreError = Exception

try:  # Optional dependency
    from google.cloud import storage as gcs_storage
    from google.cloud.exceptions import GoogleCloudError
except ImportError:  # pragma: no cover - optional
    gcs_storage = None
    GoogleCloudError = Exception

logger = logging.getLogger(__name__)


class ObjectStorageError(RuntimeError):
    """Raised when a document cannot be persisted to object storage."""


class ObjectStorageClient:
    """Persist raw source documents to S3, GCS, or local disk."""

    def __init__(self) -> None:
        self.backend = (settings.STORAGE_BACKEND or "local").lower()
        self._s3 = None
        self._gcs_bucket = None

        if self.backend == "s3" and boto3:
            self._s3 = boto3.client(
                "s3",
                region_name=settings.S3_REGION,
                endpoint_url=str(settings.S3_ENDPOINT_URL) if settings.S3_ENDPOINT_URL else None,
            )
        elif self.backend == "gcs" and gcs_storage:
            if not settings.GOOGLE_SERVICE_ACCOUNT_FILE:
                raise ObjectStorageError("GOOGLE_SERVICE_ACCOUNT_FILE required for GCS storage backend")
            self._gcs_client = gcs_storage.Client.from_service_account_json(str(settings.GOOGLE_SERVICE_ACCOUNT_FILE))
            self._gcs_bucket = self._gcs_client.bucket(settings.GCS_BUCKET_NAME or "")
        else:
            local_root = Path(settings.LOCAL_STORAGE_PATH)
            local_root.mkdir(parents=True, exist_ok=True)
            self._local_root = local_root

    async def store(self, document_id: str, content: bytes, metadata: Dict[str, str]) -> Optional[str]:
        if not content:
            logger.warning("Empty content received for document %s; skipping storage.", document_id)
            return None

        if self.backend == "s3":
            return await self._store_s3(document_id, content, metadata)
        if self.backend == "gcs":
            return await self._store_gcs(document_id, content, metadata)
        return await self._store_local(document_id, content, metadata)

    async def _store_s3(self, document_id: str, content: bytes, metadata: Dict[str, str]) -> Optional[str]:
        if not settings.S3_BUCKET_NAME or not self._s3:
            raise ObjectStorageError("S3 storage requested but configuration is incomplete")

        key = self._build_object_key(document_id, metadata)

        def upload() -> None:
            try:
                self._s3.put_object(
                    Bucket=settings.S3_BUCKET_NAME,
                    Key=key,
                    Body=content,
                    Metadata={k: str(v) for k, v in metadata.items() if isinstance(v, (str, int, float))},
                )
            except (ClientError, BotoCoreError) as exc:
                raise ObjectStorageError(f"S3 upload failed: {exc}") from exc

        await asyncio.to_thread(upload)
        return f"s3://{settings.S3_BUCKET_NAME}/{key}"

    async def _store_gcs(self, document_id: str, content: bytes, metadata: Dict[str, str]) -> Optional[str]:
        if not settings.GCS_BUCKET_NAME or not self._gcs_bucket:
            raise ObjectStorageError("GCS storage requested but configuration is incomplete")

        blob_name = self._build_object_key(document_id, metadata)

        def upload() -> None:
            try:
                blob = self._gcs_bucket.blob(blob_name)
                blob.metadata = {k: str(v) for k, v in metadata.items() if isinstance(v, (str, int, float))}
                blob.upload_from_string(content)
            except GoogleCloudError as exc:
                raise ObjectStorageError(f"GCS upload failed: {exc}") from exc

        await asyncio.to_thread(upload)
        return f"gs://{settings.GCS_BUCKET_NAME}/{blob_name}"

    async def _store_local(self, document_id: str, content: bytes, metadata: Dict[str, str]) -> Optional[str]:
        root = getattr(self, "_local_root", Path("storage"))
        filename = self._build_local_filename(document_id, metadata)
        destination = root / filename

        def write() -> None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with open(destination, "wb") as handle:
                handle.write(content)

        await asyncio.to_thread(write)
        return str(destination.resolve())

    def _build_object_key(self, document_id: str, metadata: Dict[str, str]) -> str:
        source = metadata.get("source", "unknown")
        safe_source = "".join(ch if ch.isalnum() or ch in "-_/." else "_" for ch in source.lower())
        return f"{safe_source}/{document_id}"

    def _build_local_filename(self, document_id: str, metadata: Dict[str, str]) -> str:
        extension = self._guess_extension(metadata.get("mime_type", ""))
        source = metadata.get("source", "unknown").replace("/", "_")
        return os.path.join(source, f"{document_id}{extension}")

    @staticmethod
    def _guess_extension(mime_type: str) -> str:
        mapping = {
            "application/pdf": ".pdf",
            "text/markdown": ".md",
            "text/html": ".html",
            "application/json": ".json",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        }
        return mapping.get(mime_type, ".bin")
