"""Knowledge ingestion pipeline."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from elasticsearch import AsyncElasticsearch

from backend.core.config import settings
from backend.core.database import database_manager
from backend.knowledge.graph.manager import graph_manager
from backend.knowledge.ingestion.chunkers import TextChunker
from backend.knowledge.ingestion.extractors import EntityExtractor, MetadataExtractor
from backend.knowledge.ingestion.parsers import ParsedDocument, DocumentParser
from backend.knowledge.ingestion.storage import ObjectStorageClient, ObjectStorageError
from backend.knowledge.vector.embeddings import EmbeddingGenerator
from backend.knowledge.vector.index import vector_index

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(self) -> None:
        self.parser = DocumentParser()
        self.entity_extractor = EntityExtractor()
        self.metadata_extractor = MetadataExtractor()
        self.chunker = TextChunker()
        self.embedder = EmbeddingGenerator()
        self.storage = ObjectStorageClient()
        self.es = AsyncElasticsearch(str(settings.ELASTICSEARCH_URL))

    async def ingest_document(self, source: str, content: bytes, metadata: Dict[str, object]):
        document_id = str(metadata.get("id") or uuid.uuid4())
        mime_type = str(metadata.get("mime_type") or "text/plain")

        # 1. Parse document
        parsed = await self.parser.parse(content, mime_type)

        # 2. Extract entities and metadata
        entities = await self.extract_entities(parsed.text)
        enriched_metadata = await self.extract_metadata(parsed)
        enriched_metadata.update(
            {
                "source": source,
                "document_id": document_id,
                "ingested_at": datetime.utcnow().isoformat(),
            }
        )

        # 3. Persist raw binary to object storage
        blob_uri = await self._persist_raw_blob(document_id, source, mime_type, content, metadata)
        if blob_uri:
            enriched_metadata["blob_uri"] = blob_uri

        # 4. Chunk with overlap
        chunks = self.chunk_text(parsed.text, chunk_size=512, overlap=128)

        # 5. Generate embeddings
        embeddings = await self.generate_embeddings(chunks)

        document_payload = {
            "id": document_id,
            "title": metadata.get("title", "Untitled"),
            "source": source,
            "uri": metadata.get("uri") or blob_uri,
            "tags": metadata.get("tags", []),
            "metadata": enriched_metadata,
        }

        # 6. Update knowledge graph
        await self.update_graph(entities, document_payload)

        # 7. Store in vector database
        await self.store_vectors(chunks, embeddings, document_payload)

        # 8. Index for search
        await self.index_for_search(parsed, document_payload)

        # 9. Persist metadata and audit trail
        await self.persist_blob_metadata(document_payload, parsed)
        await self.create_audit_record(source, document_payload)

        return document_id

    def chunk_text(self, text: str, chunk_size: int, overlap: int):
        return self.chunker.chunk(text, chunk_size=chunk_size, overlap=overlap)

    async def generate_embeddings(self, chunks: List[str]):
        if not chunks:
            return []
        return await self.embedder.generate(chunks)

    async def extract_entities(self, text: str):
        return await self.entity_extractor.extract(text)

    async def extract_metadata(self, parsed_document: ParsedDocument):
        return await self.metadata_extractor.extract(parsed_document)

    async def update_graph(self, entities, document_payload):
        await graph_manager.upsert_document(document_payload, entities)

    async def store_vectors(self, chunks, embeddings, document_payload):
        vectors = []
        for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            vectors.append(
                (
                    f"{document_payload['id']}::{idx}",
                    embedding,
                    {
                        "document_id": document_payload["id"],
                        "chunk": chunk,
                        "source": document_payload["source"],
                        "title": document_payload.get("title"),
                        "uri": document_payload.get("uri"),
                    },
                )
            )
        await vector_index.upsert(namespace="documents", vectors=vectors)

    async def index_for_search(self, parsed: ParsedDocument, document_payload: Dict[str, object]):
        try:
            await self.es.index(
                index="twinops-documents",
                id=document_payload["id"],
                document={
                    "document_id": document_payload["id"],
                    "title": document_payload.get("title"),
                    "content": parsed.text,
                    "source": document_payload["source"],
                    **parsed.metadata,
                    **document_payload.get("metadata", {}),
                },
            )
        except Exception as exc:  # pragma: no cover - Elasticsearch not available during tests
            logger.error("Failed to index document in Elasticsearch: %s", exc)

    async def create_audit_record(self, source: str, document_payload: Dict[str, object]):
        mongodb = database_manager.mongodb
        if mongodb is None:
            logger.warning("MongoDB client unavailable; skipping audit record.")
            return
        await mongodb["twinops"]["ingestion_audit"].insert_one(
            {
                "document_id": document_payload["id"],
                "source": source,
                "metadata": document_payload.get("metadata", {}),
                "created_at": datetime.utcnow(),
            }
        )

    async def persist_blob_metadata(self, document_payload: Dict[str, object], parsed: ParsedDocument) -> None:
        mongodb = database_manager.mongodb
        if mongodb is None:
            return
        record = {
            "document_id": document_payload["id"],
            "title": document_payload.get("title"),
            "source": document_payload.get("source"),
            "uri": document_payload.get("uri"),
            "metadata": document_payload.get("metadata", {}),
            "parser_metadata": parsed.metadata,
            "updated_at": datetime.utcnow(),
        }
        await mongodb["twinops"]["raw_documents"].update_one(
            {"document_id": document_payload["id"]},
            {"$set": record},
            upsert=True,
        )

    async def _persist_raw_blob(
        self,
        document_id: str,
        source: str,
        mime_type: str,
        content: bytes,
        metadata: Dict[str, object],
    ) -> Optional[str]:
        try:
            return await self.storage.store(
                document_id=document_id,
                content=content,
                metadata={
                    "source": source,
                    "mime_type": mime_type,
                    "title": str(metadata.get("title", "")),
                },
            )
        except ObjectStorageError as exc:
            logger.error("Unable to persist raw document %s: %s", document_id, exc)
            return None
