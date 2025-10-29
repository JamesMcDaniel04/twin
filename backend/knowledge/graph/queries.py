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

# Container-specific queries

UPSERT_CONTAINER_IMAGE = """
MERGE (img:ContainerImage {image_id: $image_id})
SET img += {
    tag: $tag,
    repository: $repository,
    artifact_uri: $artifact_uri,
    version: $version,
    base_image: $base_image,
    runtime: $runtime,
    owner_team: $owner_team,
    labels: $labels,
    build_info: $build_info,
    ingested_at: datetime()
}
WITH img
FOREACH (_ IN CASE WHEN $owner_team IS NOT NULL THEN [1] ELSE [] END |
    MERGE (team:Team {name: $owner_team})
    MERGE (img)-[:OWNED_BY]->(team)
    MERGE (team)-[:OWNS]->(img)
)
RETURN img
"""

UPSERT_SBOM = """
MERGE (sbom:SBOM {sbom_id: $sbom_id})
SET sbom += {
    uri: $uri,
    format: $format,
    version: $version,
    created_at: datetime()
}
RETURN sbom
"""

LINK_CONTAINER_TO_SBOM = """
MATCH (img:ContainerImage {image_id: $image_id})
MATCH (sbom:SBOM {uri: $sbom_uri})
MERGE (img)-[:HAS_SBOM]->(sbom)
MERGE (sbom)-[:DESCRIBES]->(img)
RETURN img, sbom
"""

LINK_CONTAINER_TO_DOCUMENT = """
MATCH (img:ContainerImage {image_id: $image_id})
MATCH (doc:Document {id: $document_id})
MERGE (img)-[:DOCUMENTED_IN]->(doc)
MERGE (doc)-[:DOCUMENTS]->(img)
RETURN img, doc
"""

LINK_SERVICE_TO_CONTAINER = """
MERGE (svc:Service {name: $service_name, namespace: $namespace})
SET svc += {
    cluster: $cluster,
    team: $team
}
WITH svc
MATCH (img:ContainerImage {image_id: $image_id})
MERGE (svc)-[:RUNS]->(img)
MERGE (img)-[:DEPLOYED_IN]->(svc)
WITH svc
FOREACH (_ IN CASE WHEN $team IS NOT NULL THEN [1] ELSE [] END |
    MERGE (team:Team {name: $team})
    MERGE (svc)-[:OWNED_BY]->(team)
    MERGE (team)-[:OWNS]->(svc)
)
RETURN svc
"""

UPSERT_VULNERABILITY = """
MERGE (vuln:Vulnerability {cve_id: $cve_id})
SET vuln += {
    severity: $severity,
    package: $package,
    version: $version,
    fixed_version: $fixed_version,
    description: $description,
    updated_at: datetime()
}
RETURN vuln
"""

LINK_VULNERABILITY_TO_CONTAINER = """
MATCH (img:ContainerImage {image_id: $image_id})
MATCH (vuln:Vulnerability {cve_id: $cve_id})
MERGE (img)-[rel:HAS_VULNERABILITY]->(vuln)
SET rel.severity = $severity,
    rel.detected_at = datetime()
MERGE (vuln)-[:AFFECTS]->(img)
RETURN img, vuln
"""
