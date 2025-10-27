"""Google Workspace ingestion worker."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from backend.core.config import settings
from backend.knowledge.ingestion.workers.base import BaseIngestionWorker

logger = logging.getLogger(__name__)


class GoogleWorkspaceIngestionWorker(BaseIngestionWorker):
    source = "google_workspace"

    def __init__(self, drive_file_ids: Optional[List[str]] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.drive_file_ids = drive_file_ids or settings.GOOGLE_DRIVE_FILE_IDS
        self._credentials = None

    async def run(self) -> None:
        if not self.drive_file_ids:
            logger.warning("Skipping Google Workspace ingestion; GOOGLE_DRIVE_FILE_IDS is empty.")
            return
        if not settings.GOOGLE_SERVICE_ACCOUNT_FILE:
            logger.warning("Skipping Google Workspace ingestion; GOOGLE_SERVICE_ACCOUNT_FILE not set.")
            return

        service = await asyncio.to_thread(self._build_drive_service)

        for file_id in self.drive_file_ids:
            await self._ingest_drive_file(service, file_id.strip())

    def _build_drive_service(self):
        scopes = [
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        credentials = service_account.Credentials.from_service_account_file(
            str(settings.GOOGLE_SERVICE_ACCOUNT_FILE),
            scopes=scopes,
        )
        self._credentials = credentials
        return build("drive", "v3", credentials=credentials, cache_discovery=False)

    async def _ingest_drive_file(self, service, file_id: str) -> None:
        if not file_id:
            return

        file_metadata = await asyncio.to_thread(
            lambda: service.files().get(fileId=file_id, fields="id,name,mimeType,webViewLink").execute()
        )

        mime_type = file_metadata.get("mimeType", "application/octet-stream")
        name = file_metadata.get("name", file_id)
        link = file_metadata.get("webViewLink")

        content = await asyncio.to_thread(self._download_drive_file, service, file_id)
        if content is None:
            return

        metadata = {
            "id": file_id,
            "title": name,
            "mime_type": mime_type,
            "tags": ["google", "workspace"],
            "uri": link,
        }
        await self.process_document(file_id, content, metadata)

    def _download_drive_file(self, service, file_id: str) -> Optional[bytes]:
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        try:
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug("Download %s progress: %s%%", file_id, int(status.progress() * 100))
        except Exception as exc:  # pragma: no cover - API errors
            logger.error("Failed to download Google Drive file %s: %s", file_id, exc)
            return None

        return buffer.getvalue()
