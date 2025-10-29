# Ingestion Service Documentation

## Overview

The TwinOps Ingestion Service is a dedicated FastAPI-based microservice for ingesting documents and container artifacts into the knowledge base. It provides asynchronous, scalable ingestion backed by Temporal workflows.

## Architecture

```
┌─────────────────┐
│   Client API    │
│  /api/v1/ingest │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│  FastAPI Ingestion      │
│  Router                 │
│  - Validation           │
│  - Task Creation        │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  Temporal Workflow      │
│  (IngestionWorkflow)    │
│  - Fetch Content        │
│  - Process Pipeline     │
│  - Update Status        │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  IngestionPipeline      │
│  - Parse                │
│  - Extract Entities     │
│  - Chunk & Embed        │
│  - Store (Neo4j, etc.)  │
└─────────────────────────┘
```

## Endpoints

### 1. Ingest Document

**POST** `/api/v1/ingest`

Ingest a document or container artifact asynchronously.

#### Request Body

```json
{
  "source": "upload|s3|gcs|url|container",
  "title": "Optional document title",
  "mime_type": "application/octet-stream",
  "tags": ["tag1", "tag2"],
  "metadata": {},
  "document_bytes": "base64-encoded-content",  // For upload source
  "s3_uri": "s3://bucket/key",                 // For s3 source
  "gcs_uri": "gs://bucket/blob",               // For gcs source
  "url": "https://example.com/doc.pdf",        // For url source
  "container_metadata": {                       // For container source
    "image_id": "sha256:abc123...",
    "image_tag": "v1.0.0",
    "registry": "gcr.io",
    "repository": "myorg/backend-api",
    "sbom_uri": "s3://sboms/backend-api-v1.0.0.json",
    "sbom_format": "spdx"
  }
}
```

#### Response (202 Accepted)

```json
{
  "task_id": "uuid",
  "workflow_id": "ingestion-uuid",
  "status": "queued",
  "submitted_at": "2024-01-15T10:30:00Z"
}
```

### 2. Ingest File

**POST** `/api/v1/ingest/file`

Upload a file via multipart form data.

#### Request

- **Form Data**: `file` (multipart/form-data)
- **Optional JSON**: `metadata` field with `IngestFileRequest` structure

#### Response (202 Accepted)

Same as `/ingest` endpoint.

### 3. Get Ingestion Status

**GET** `/api/v1/ingest/{task_id}`

Query the status of an ingestion task.

#### Response

```json
{
  "task_id": "uuid",
  "status": "queued|processing|completed|failed",
  "document_id": "doc-uuid",  // Only if completed
  "error": "error message",   // Only if failed
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:35:00Z",
  "metadata": {}
}
```

### 4. List Ingestion Tasks

**GET** `/api/v1/ingest?status=queued&limit=50&offset=0`

List ingestion tasks with optional filtering.

#### Query Parameters

- `status` (optional): Filter by status
- `limit` (default: 50): Max results
- `offset` (default: 0): Pagination offset

#### Response

```json
{
  "tasks": [...],
  "total": 100,
  "limit": 50,
  "offset": 0
}
```

### 5. Delete Ingestion Task

**DELETE** `/api/v1/ingest/{task_id}`

Delete an ingestion task record (does not delete ingested document).

#### Response (204 No Content)

---

## Container Artifact Schema

Container artifacts are specialized documents with structured metadata for container images.

### ContainerImageMetadata

```python
{
  "image_id": "sha256:abc123...",           # Required: SHA256 digest
  "image_tag": "v1.0.0",                     # Required: Tag name
  "registry": "gcr.io",                      # Required: Registry URL
  "repository": "myorg/backend-api",         # Required: Repository name
  "sbom_uri": "s3://sboms/...",              # Optional: SBOM URI
  "sbom_format": "spdx|cyclonedx",           # Optional: SBOM format
  "created_at": "2024-01-15T10:30:00Z",      # Optional: Creation timestamp
  "size_bytes": 1234567,                     # Optional: Image size
  "architecture": "amd64",                   # Optional: CPU arch
  "os": "linux",                             # Optional: OS
  "layers": ["sha256:...", ...],             # Optional: Layer digests
  "labels": {"key": "value"},                # Optional: Image labels
  "env_vars": {"KEY": "value"},              # Optional: Environment vars
  "vulnerabilities": {                        # Optional: Vulnerability scan
    "CVE-2024-1234": {
      "severity": "critical",
      "package": "libssl",
      "version": "1.0.0",
      "fixed_version": "1.0.1",
      "description": "..."
    }
  }
}
```

---

## Neo4j Graph Schema

Container artifacts create a rich graph structure:

### Nodes

- **ContainerImage**: Image metadata
- **SBOM**: SBOM document metadata
- **Vulnerability**: CVE information
- **Document**: Associated documentation
- **Service**: Kubernetes services running the image
- **Team**: Owning team

### Relationships

- `ContainerImage -[:HAS_SBOM]-> SBOM`
- `ContainerImage -[:HAS_VULNERABILITY]-> Vulnerability`
- `ContainerImage -[:DOCUMENTED_IN]-> Document`
- `Service -[:RUNS]-> ContainerImage`
- `Team -[:OWNS]-> ContainerImage`

---

## Storage

### Object Storage

Container artifacts are persisted to object storage (S3/GCS/local):

1. **Container Metadata**: `container-artifact-{artifact_id}` (JSON)
2. **Dockerfile**: `dockerfile-{artifact_id}` (plain text)
3. **SBOM**: `sbom-{artifact_id}` (JSON)

### Vector Indexing

Document chunks are embedded and indexed in Pinecone for semantic search.

### Full-Text Search

Documents are indexed in Elasticsearch for keyword search.

### Graph Database

Container metadata and relationships are stored in Neo4j for:
- Dependency tracking
- Vulnerability impact analysis
- Service-to-container mapping

---

## Temporal Workflow

The `IngestionWorkflow` orchestrates the ingestion process with retry policies:

1. **Update Status** → `processing`
2. **Fetch Document Content** (10min timeout)
   - From S3, GCS, URL, or base64
3. **Ingest to Knowledge Base** (30min timeout)
   - Parse document
   - Extract entities
   - Chunk & embed
   - Store in Neo4j, Pinecone, Elasticsearch, MongoDB
4. **Update Status** → `completed` or `failed`

### Retry Policy

- Initial interval: 1 second
- Maximum interval: 60 seconds
- Maximum attempts: 3
- Backoff coefficient: 2.0

---

## Example: Ingest Container Artifact

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source": "container",
    "tags": ["production", "backend"],
    "container_metadata": {
      "image_id": "sha256:abc123def456...",
      "image_tag": "v2.1.0",
      "registry": "gcr.io",
      "repository": "myorg/backend-api",
      "sbom_uri": "s3://my-bucket/sboms/backend-api-v2.1.0-spdx.json",
      "sbom_format": "spdx",
      "architecture": "amd64",
      "os": "linux",
      "vulnerabilities": {
        "CVE-2024-1234": {
          "severity": "high",
          "package": "openssl",
          "version": "1.1.1",
          "fixed_version": "1.1.1k"
        }
      }
    }
  }'
```

### Response

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "workflow_id": "ingestion-550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "submitted_at": "2024-01-15T10:30:00.000Z"
}
```

---

## Querying Container Artifacts

Use the GraphManager to query container artifacts:

```python
from backend.knowledge.graph.manager import graph_manager

# Query by registry
artifacts = await graph_manager.query_container_artifacts(
    registry="gcr.io",
    limit=50
)

# Query by repository
artifacts = await graph_manager.query_container_artifacts(
    repository="myorg/backend-api",
    tag="v2.1.0"
)
```

---

## Monitoring & Observability

### OpenTelemetry Tracing

All ingestion operations are traced with spans:
- `ingestion.ingest_document`
- `ingestion.parse`
- `ingestion.entities`
- `ingestion.embed`
- `ingestion.update_graph`

### Prometheus Metrics

Expose metrics at `/metrics`:
- `ingestion_tasks_total{status}`
- `ingestion_duration_seconds`
- `ingestion_documents_processed_total`

### Logging

Structured logs via `structlog`:
```json
{
  "event": "ingestion_completed",
  "task_id": "uuid",
  "document_id": "doc-uuid",
  "execution_time_ms": 1234,
  "timestamp": "2024-01-15T10:35:00Z"
}
```

---

## Error Handling

### Common Errors

1. **400 Bad Request**: Invalid request body or missing required fields
2. **404 Not Found**: Task ID not found
3. **500 Internal Server Error**: Workflow execution failed
4. **503 Service Unavailable**: Database unavailable

### Workflow Failures

Failures are logged and status updated to `failed` with error message. Check task status for details.

---

## Configuration

### Environment Variables

```bash
# Temporal
TEMPORAL_HOST=localhost:7233
TEMPORAL_NAMESPACE=twinops
TEMPORAL_TASK_QUEUE=twinops-workflows

# Storage
STORAGE_BACKEND=s3  # local|s3|gcs
S3_BUCKET_NAME=my-bucket
S3_REGION=us-west-2

# Databases
NEO4J_URI=neo4j://localhost:7687
PINECONE_API_KEY=...
ELASTICSEARCH_URL=http://localhost:9200
MONGODB_URL=mongodb://localhost:27017
```

---

## Best Practices

1. **Large Files**: Use S3/GCS URIs instead of base64 encoding
2. **SBOM Storage**: Store SBOMs separately and reference via URI
3. **Batch Ingestion**: Submit multiple tasks concurrently; Temporal handles scaling
4. **Vulnerability Scanning**: Integrate with Trivy/Grype and ingest scan results
5. **Monitoring**: Track ingestion metrics and set alerts for failures

---

## Next Steps

1. **Integration**: Connect with CI/CD pipelines to auto-ingest on image push
2. **SBOM Parsing**: Implement SPDX/CycloneDX parsers for detailed dependency tracking
3. **Policy Enforcement**: Add validation rules for container artifacts
4. **Retention**: Implement TTL policies for old artifact versions
