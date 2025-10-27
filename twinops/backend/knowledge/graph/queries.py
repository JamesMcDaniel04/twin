"""Cypher query templates for TwinOps graph operations."""

UPSERT_DOCUMENT = """
MERGE (d:Document {id: $id})
SET d += {
    title: $title,
    source: $source,
    uri: $uri,
    tags: $tags,
    metadata: $metadata
}
"""

LINK_ENTITY = """
UNWIND $entities AS entity
MERGE (e:Entity {id: entity.id})
SET e += {name: entity.name, type: entity.type}
WITH e
MATCH (d:Document {id: $document_id})
MERGE (e)-[:MENTIONS]->(d)
"""
