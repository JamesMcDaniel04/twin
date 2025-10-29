"""Storage client for container artifacts with SBOM support."""

from __future__ import annotations

import json
import logging
from typing import Dict, Optional

from backend.knowledge.ingestion.storage import ObjectStorageClient, ObjectStorageError

logger = logging.getLogger(__name__)


class ContainerArtifactStorage:
    """Storage client specialized for container artifacts with SBOM pointers."""

    def __init__(self) -> None:
        self.storage = ObjectStorageClient()

    async def store_artifact(
        self,
        artifact_id: str,
        container_metadata: Dict[str, object],
        dockerfile: Optional[str] = None,
        sbom_content: Optional[bytes] = None,
    ) -> Dict[str, str]:
        """
        Store container artifact metadata and optional SBOM.

        Args:
            artifact_id: Unique artifact identifier
            container_metadata: Container image metadata (image_id, tag, etc.)
            dockerfile: Optional Dockerfile content
            sbom_content: Optional SBOM document bytes (SPDX/CycloneDX)

        Returns:
            Dictionary with URIs:
                - artifact_uri: URI to artifact metadata JSON
                - dockerfile_uri: URI to Dockerfile (if provided)
                - sbom_uri: URI to SBOM document (if provided)

        Raises:
            ObjectStorageError: If storage operation fails
        """
        uris = {}

        # Store artifact metadata as JSON
        metadata_json = json.dumps(container_metadata, indent=2).encode("utf-8")
        try:
            artifact_uri = await self.storage.store(
                document_id=f"container-artifact-{artifact_id}",
                content=metadata_json,
                metadata={
                    "content_type": "application/json",
                    "artifact_type": "container_metadata",
                    "image_id": container_metadata.get("image_id", ""),
                    "image_tag": container_metadata.get("image_tag", ""),
                },
            )
            uris["artifact_uri"] = artifact_uri
            logger.info(f"Stored container artifact metadata: {artifact_uri}")
        except ObjectStorageError as exc:
            logger.error(f"Failed to store artifact metadata: {exc}")
            raise

        # Store Dockerfile if provided
        if dockerfile:
            try:
                dockerfile_uri = await self.storage.store(
                    document_id=f"dockerfile-{artifact_id}",
                    content=dockerfile.encode("utf-8"),
                    metadata={
                        "content_type": "text/plain",
                        "artifact_type": "dockerfile",
                        "artifact_id": artifact_id,
                    },
                )
                uris["dockerfile_uri"] = dockerfile_uri
                logger.info(f"Stored Dockerfile: {dockerfile_uri}")
            except ObjectStorageError as exc:
                logger.warning(f"Failed to store Dockerfile: {exc}")

        # Store SBOM if provided
        if sbom_content:
            try:
                sbom_uri = await self.storage.store(
                    document_id=f"sbom-{artifact_id}",
                    content=sbom_content,
                    metadata={
                        "content_type": "application/json",
                        "artifact_type": "sbom",
                        "artifact_id": artifact_id,
                    },
                )
                uris["sbom_uri"] = sbom_uri
                logger.info(f"Stored SBOM: {sbom_uri}")
            except ObjectStorageError as exc:
                logger.warning(f"Failed to store SBOM: {exc}")

        return uris

    async def retrieve_artifact(self, artifact_id: str) -> Optional[Dict[str, object]]:
        """
        Retrieve container artifact metadata.

        Args:
            artifact_id: Artifact identifier

        Returns:
            Container metadata dictionary or None if not found
        """
        try:
            content = await self.storage.retrieve(f"container-artifact-{artifact_id}")
            if content:
                return json.loads(content.decode("utf-8"))
            return None
        except Exception as exc:
            logger.error(f"Failed to retrieve artifact {artifact_id}: {exc}")
            return None

    async def retrieve_sbom(self, artifact_id: str) -> Optional[bytes]:
        """
        Retrieve SBOM document for a container artifact.

        Args:
            artifact_id: Artifact identifier

        Returns:
            SBOM document bytes or None if not found
        """
        try:
            return await self.storage.retrieve(f"sbom-{artifact_id}")
        except Exception as exc:
            logger.error(f"Failed to retrieve SBOM for artifact {artifact_id}: {exc}")
            return None

    async def retrieve_dockerfile(self, artifact_id: str) -> Optional[str]:
        """
        Retrieve Dockerfile content for a container artifact.

        Args:
            artifact_id: Artifact identifier

        Returns:
            Dockerfile content string or None if not found
        """
        try:
            content = await self.storage.retrieve(f"dockerfile-{artifact_id}")
            if content:
                return content.decode("utf-8")
            return None
        except Exception as exc:
            logger.error(f"Failed to retrieve Dockerfile for artifact {artifact_id}: {exc}")
            return None
