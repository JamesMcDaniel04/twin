"""Graph operations manager."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from neo4j import AsyncSession

from backend.core.config import settings
from backend.core.database import database_manager
from backend.knowledge.graph import queries

logger = logging.getLogger(__name__)


class GraphManager:
    """High-level graph operations for knowledge ingestion and context expansion."""

    def __init__(self) -> None:
        self._document_locks: Dict[str, asyncio.Lock] = {}
        self._lock_guard = asyncio.Lock()

    async def upsert_document(self, document: Dict[str, object], entities: List[Dict[str, object]]) -> None:
        """Create or update a document node and attach related entities."""

        driver = database_manager.neo4j
        if driver is None:
            logger.warning("Neo4j driver not initialized; skipping graph update.")
            return

        document_id = str(document["id"])
        lock = await self._acquire_lock(document_id)
        try:
            async with lock:
                async with driver.session() as session:  # type: AsyncSession
                    await session.execute_write(self._write_document, document)
                    if entities:
                        await session.execute_write(self._link_entities, document_id, entities)

                    # Handle container-specific metadata
                    metadata = document.get("metadata", {})
                    if metadata.get("image_id"):
                        await session.execute_write(self._write_container_image, document_id, metadata)
        finally:
            await self._release_lock(document_id, lock)

    async def expand_context(
        self,
        query: str,
        *,
        limit: int = 25,
        max_depth: Optional[int] = None,
    ) -> List[Dict[str, object]]:
        """Return graph context for the provided query using APOC traversals."""

        driver = database_manager.neo4j
        if driver is None:
            logger.debug("Neo4j driver unavailable; returning empty graph context.")
            return []

        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return []

        traversal_depth = max_depth or settings.GRAPH_TRAVERSAL_MAX_DEPTH
        seed_limit = min(limit * 4, 100)

        async with driver.session() as session:  # type: AsyncSession
            result = await session.run(
                queries.APOC_TRAVERSE_CONTEXT,
                {
                    "terms": terms,
                    "limit": limit,
                    "max_depth": traversal_depth,
                    "seed_limit": seed_limit,
                },
            )
            records = await result.data()

        aggregated: Dict[str, Dict[str, object]] = {}
        for record in records:
            document_id = record["document_id"]
            entry = aggregated.setdefault(
                document_id,
                {
                    "document_id": document_id,
                    "title": record.get("title"),
                    "source": record.get("source"),
                    "nodes": set(),
                    "seed_entities": set(),
                    "relationships": [],
                    "metadata": (record.get("metadata") or {}) | {},
                },
            )
            entry["seed_entities"].add(record.get("seed_entity"))
            entry["nodes"].update(record.get("entities", []))
            entry["relationships"].extend(record.get("relationships", []))
            current_metadata = entry["metadata"]
            new_metadata = record.get("metadata") or {}
            for key, value in new_metadata.items():
                # Preserve the first non-empty metadata value.
                current_metadata.setdefault(key, value)

        context: List[Dict[str, object]] = []
        for payload in aggregated.values():
            relationships = [
                rel
                for rel in payload["relationships"]
                if rel and rel.get("start") is not None and rel.get("end") is not None
            ]
            deduped = {(rel["type"], rel["start"], rel["end"]): rel for rel in relationships}
            payload["relationships"] = list(deduped.values())
            payload["nodes"] = sorted(filter(None, payload["nodes"]))
            payload["seed_entities"] = sorted(filter(None, payload["seed_entities"]))
            context.append(payload)

        return context

    async def _acquire_lock(self, doc_id: str) -> asyncio.Lock:
        async with self._lock_guard:
            lock = self._document_locks.get(doc_id)
            if lock is None:
                lock = asyncio.Lock()
                self._document_locks[doc_id] = lock
            return lock

    async def _release_lock(self, doc_id: str, lock: asyncio.Lock) -> None:
        async with self._lock_guard:
            current = self._document_locks.get(doc_id)
            if current is lock and not lock.locked():
                self._document_locks.pop(doc_id, None)

    @staticmethod
    async def _write_document(tx, document: Dict[str, object]) -> None:
        await tx.run(
            queries.UPSERT_DOCUMENT,
            {
                "id": document["id"],
                "title": document["title"],
                "source": document.get("source"),
                "uri": document.get("uri"),
                "tags": document.get("tags", []),
                "metadata": document.get("metadata", {}),
            },
        )

    @staticmethod
    async def _link_entities(tx, document_id: str, entities: List[Dict[str, object]]) -> None:
        await tx.run(
            queries.LINK_ENTITIES,
            {"entities": entities, "document_id": document_id},
        )

    @staticmethod
    async def _write_container_image(tx, document_id: str, metadata: Dict[str, object]) -> None:
        """Write container image node and link to document."""
        image_id = metadata.get("image_id")
        if not image_id:
            return

        # Create container image node
        await tx.run(
            queries.UPSERT_CONTAINER_IMAGE,
            {
                "image_id": image_id,
                "tag": metadata.get("image_tag"),
                "repository": metadata.get("repository"),
                "artifact_uri": metadata.get("artifact_uri"),
                "version": metadata.get("image_tag"),
                "base_image": metadata.get("base_image"),
                "runtime": metadata.get("runtime"),
                "owner_team": metadata.get("owner_team"),
                "labels": metadata.get("labels", {}),
                "build_info": metadata.get("build_context", {}),
            },
        )

        # Link container to document
        await tx.run(
            queries.LINK_CONTAINER_TO_DOCUMENT,
            {"image_id": image_id, "document_id": document_id},
        )

        # Create SBOM node if SBOM URI exists
        sbom_uri = metadata.get("sbom_uri")
        if sbom_uri:
            await tx.run(
                queries.UPSERT_SBOM,
                {
                    "sbom_id": f"sbom-{image_id}",
                    "uri": sbom_uri,
                    "format": metadata.get("sbom_format", "unknown"),
                    "version": "1.0",
                },
            )
            await tx.run(
                queries.LINK_CONTAINER_TO_SBOM,
                {"image_id": image_id, "sbom_uri": sbom_uri},
            )

        # Link vulnerabilities if present
        vulnerabilities = metadata.get("vulnerabilities", {})
        if isinstance(vulnerabilities, dict):
            for cve_id, vuln_data in vulnerabilities.items():
                await tx.run(
                    queries.UPSERT_VULNERABILITY,
                    {
                        "cve_id": cve_id,
                        "severity": vuln_data.get("severity", "unknown"),
                        "package": vuln_data.get("package", ""),
                        "version": vuln_data.get("version", ""),
                        "fixed_version": vuln_data.get("fixed_version"),
                        "description": vuln_data.get("description", ""),
                    },
                )
                await tx.run(
                    queries.LINK_VULNERABILITY_TO_CONTAINER,
                    {
                        "image_id": image_id,
                        "cve_id": cve_id,
                        "severity": vuln_data.get("severity", "unknown"),
                    },
                )

    async def query_container_artifacts(
        self,
        registry: Optional[str] = None,
        repository: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, object]]:
        """
        Query container artifacts from the graph.

        Args:
            registry: Filter by registry URL
            repository: Filter by repository name
            tag: Filter by image tag
            limit: Maximum results

        Returns:
            List of container artifacts with metadata
        """
        driver = database_manager.neo4j
        if driver is None:
            logger.warning("Neo4j driver not initialized")
            return []

        # Build dynamic WHERE clauses
        where_clauses = []
        params = {"limit": limit}

        if registry:
            where_clauses.append("img.repository CONTAINS $registry")
            params["registry"] = registry
        if repository:
            where_clauses.append("img.repository = $repository")
            params["repository"] = repository
        if tag:
            where_clauses.append("img.tag = $tag")
            params["tag"] = tag

        where_clause = " AND ".join(where_clauses) if where_clauses else "true"

        query = f"""
        MATCH (img:ContainerImage)
        WHERE {where_clause}
        OPTIONAL MATCH (img)-[:HAS_SBOM]->(sbom:SBOM)
        OPTIONAL MATCH (img)-[:HAS_VULNERABILITY]->(vuln:Vulnerability)
        OPTIONAL MATCH (img)-[:DOCUMENTED_IN]->(doc:Document)
        RETURN img,
               collect(DISTINCT sbom) as sboms,
               collect(DISTINCT vuln) as vulnerabilities,
               collect(DISTINCT doc) as documents
        LIMIT $limit
        """

        async with driver.session() as session:  # type: AsyncSession
            result = await session.run(query, params)
            records = await result.data()

        artifacts = []
        for record in records:
            img = record["img"]
            artifacts.append(
                {
                    "image_id": img.get("image_id"),
                    "tag": img.get("tag"),
                    "repository": img.get("repository"),
                    "artifact_uri": img.get("artifact_uri"),
                    "labels": img.get("labels", {}),
                    "sboms": [s.get("uri") for s in record.get("sboms", []) if s],
                    "vulnerabilities": [
                        {
                            "cve_id": v.get("cve_id"),
                            "severity": v.get("severity"),
                            "package": v.get("package"),
                        }
                        for v in record.get("vulnerabilities", [])
                        if v
                    ],
                    "documents": [d.get("id") for d in record.get("documents", []) if d],
                }
            )

        return artifacts


graph_manager = GraphManager()
