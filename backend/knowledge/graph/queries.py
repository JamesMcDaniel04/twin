"""Cypher query templates for TwinOps graph operations."""

UPSERT_DOCUMENT = """
MERGE (d:Document {id: $id})
SET d += {
    title: $title,
    source: $source,
    uri: $uri,
    tags: $tags,
    metadata: $metadata,
    last_ingested_at: datetime()
}
WITH d
FOREACH (_ IN CASE WHEN $source IS NOT NULL THEN [1] ELSE [] END |
    MERGE (s:Source {name: $source})
    MERGE (d)-[:ORIGINATES_FROM]->(s)
    MERGE (s)-[:PRODUCED]->(d)
)
FOREACH (tag IN $tags |
    MERGE (t:Tag {name: tag})
    MERGE (d)-[:TAGGED]->(t)
    MERGE (t)-[:TAGGED_DOCUMENT]->(d)
)
RETURN d
"""

LINK_ENTITIES = """
MATCH (d:Document {id: $document_id})
WITH d, $entities AS entities
UNWIND entities AS entity
MERGE (e:Entity {id: entity.id})
SET e += {
    name: entity.name,
    type: entity.type,
    synonyms: coalesce(entity.synonyms, []),
    salience: coalesce(entity.salience, 0.0),
    updated_at: datetime()
}
FOREACH (alias IN coalesce(entity.aliases, []) |
    MERGE (a:Alias {name: alias})
    MERGE (e)-[:HAS_ALIAS]->(a)
)
MERGE (e)-[rel_out:MENTIONS]->(d)
SET rel_out.confidence = coalesce(entity.confidence, 0.7),
    rel_out.metadata = coalesce(entity.metadata, {})
MERGE (d)-[rel_in:MENTIONS]->(e)
SET rel_in.confidence = rel_out.confidence,
    rel_in.metadata = rel_out.metadata
WITH d, collect({node: e, payload: entity}) AS entity_payloads
UNWIND entity_payloads AS source
UNWIND entity_payloads AS target
WITH d, source, target
WHERE source.payload.id < target.payload.id
MERGE (source.node)-[co:CO_OCCURS_WITH]-(target.node)
SET co.weight = coalesce(co.weight, 0) + 1,
    co.last_seen_at = datetime()
RETURN d.id AS document_id
"""

APOC_TRAVERSE_CONTEXT = """
UNWIND $terms AS term
WITH DISTINCT toLower(term) AS normalized_term
MATCH (seed:Entity)
WHERE toLower(seed.name) CONTAINS normalized_term
WITH DISTINCT seed LIMIT $seed_limit
CALL apoc.path.expandConfig(
    seed,
    {
        relationshipFilter: "<MENTIONS|MENTIONS|RELATED>|<RELATED|CO_OCCURS_WITH",
        minLevel: 1,
        maxLevel: $max_depth,
        uniqueness: "NODE_GLOBAL"
    }
)
YIELD path
WITH seed, nodes(path) AS path_nodes, relationships(path) AS rels
WITH seed, rels, [node IN path_nodes WHERE node:Document][0] AS doc,
     [node IN path_nodes WHERE node:Entity | {id: node.id, name: node.name, type: node.type}] AS entities
WHERE doc IS NOT NULL
RETURN DISTINCT
    doc.id AS document_id,
    doc.title AS title,
    doc.source AS source,
    seed.name AS seed_entity,
    entities AS entities,
    [rel IN rels | {type: type(rel), start: startNode(rel).id, end: endNode(rel).id}] AS relationships,
    doc.metadata AS metadata
LIMIT $limit
"""
