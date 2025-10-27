"""Knowledge ingestion pipeline."""

from __future__ import annotations

import logging
import uuid
from typing import Dict, List

from elasticsearch import AsyncElasticsearch

from backend.core.config import settings
from backend.core.database import database_manager
from backend.knowledge.graph.manager import graph_manager
from backend.knowledge.ingestion.chunkers import TextChunker
from backend.knowledge.ingestion.extractors import EntityExtractor, MetadataExtractor
from backend.knowledge.ingestion.parsers import DocumentParser
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
        self.es = AsyncElasticsearch(settings.ELASTICSEARCH_URL)

    async def ingest_document(self, source: str, content: bytes, metadata: dict):
        document_id = metadata.get("id", str(uuid.uuid4()))

        # 1. Parse document
        parsed = await self.parser.parse(content, metadata.get("mime_type", "text/plain"))

        # 2. Extract entities and metadata
        entities = await self.extract_entities(parsed.text)
        enriched_metadata = await self.extract_metadata(parsed)
        enriched_metadata.update({"source": source, "document_id": document_id})

        # 3. Chunk with overlap
        chunks = self.chunk_text(parsed.text, chunk_size=512, overlap=128)

        # 4. Generate embeddings
        embeddings = await self.generate_embeddings(chunks)

        document_payload = {
            "id": document_id,
            "title": metadata.get("title", "Untitled"),
            "source": source,
            "uri": metadata.get("uri"),
            "tags": metadata.get("tags", []),
            "metadata": enriched_metadata,
        }

        # 5. Update knowledge graph
        await self.update_graph(entities, document_payload)

        # 6. Store in vector database
        await self.store_vectors(chunks, embeddings, document_payload)

        # 7. Index for search
        await self.index_for_search(parsed.text, document_payload)

        # 8. Create audit record
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

    async def extract_metadata(self, parsed_document):
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
                    },
                )
            )
        await vector_index.upsert(namespace="documents", vectors=vectors)

    async def index_for_search(self, text: str, document_payload):
        try:
            await self.es.index(
                index="twinops-documents",
                id=document_payload["id"],
                document={
                    "document_id": document_payload["id"],
                    "title": document_payload.get("title"),
                    "content": text,
                    "source": document_payload["source"],
                    **document_payload.get("metadata", {}),
                },
            )
        except Exception as exc:  # pragma: no cover - Elasticsearch not available during tests
            logger.error("Failed to index document in Elasticsearch: %s", exc)

    async def create_audit_record(self, source: str, document_payload):
        mongodb = database_manager.mongodb
        if mongodb is None:
            logger.warning("MongoDB client unavailable; skipping audit record.")
            return
        await mongodb["twinops"]["ingestion_audit"].insert_one(
            {
                "document_id": document_payload["id"],
                "source": source,
                "metadata": document_payload.get("metadata", {}),
            }
        )
