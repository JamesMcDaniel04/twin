# Quick Start Guide

## 5-Minute Setup

### Prerequisites

- Docker & Docker Compose
- Python 3.9+
- Running TwinOps stack (Neo4j, MongoDB, Temporal, etc.)

### 1. Start Services

```bash
# Start the TwinOps stack
docker-compose up -d

# Verify services are running
docker-compose ps
```

### 2. Run the API Server

```bash
cd backend
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000
```

### 3. Ingest Your First Container

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source": "container",
    "tags": ["production", "backend"],
    "container_metadata": {
      "image_id": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
      "image_tag": "v1.0.0",
      "registry": "docker.io",
      "repository": "nginx",
      "architecture": "amd64",
      "os": "linux"
    }
  }'
```

**Response:**
```json
{
  "task_id": "abc-123",
  "workflow_id": "ingestion-abc-123",
  "status": "queued",
  "submitted_at": "2024-01-15T10:30:00Z"
}
```

### 4. Check Status

```bash
# Replace {task_id} with the value from step 3
curl http://localhost:8000/api/v1/ingest/{task_id}
```

**Response:**
```json
{
  "task_id": "abc-123",
  "status": "completed",
  "document_id": "doc-xyz-789",
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-01-15T10:31:00Z"
}
```

### 5. Query Container

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test",
    "user_id": "test-user",
    "text": "Tell me about the nginx container"
  }'
```

---

## Common Use Cases

### Ingest from S3

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source": "s3",
    "s3_uri": "s3://my-bucket/documents/architecture.pdf",
    "title": "System Architecture",
    "tags": ["documentation", "architecture"]
  }'
```

### Ingest with SBOM

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source": "container",
    "container_metadata": {
      "image_id": "sha256:abc123...",
      "image_tag": "v2.0.0",
      "registry": "gcr.io",
      "repository": "myorg/api",
      "sbom_uri": "s3://my-bucket/sboms/api-v2.0.0.json",
      "sbom_format": "spdx"
    }
  }'
```

### Ingest with Vulnerabilities

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source": "container",
    "container_metadata": {
      "image_id": "sha256:abc123...",
      "image_tag": "v1.5.0",
      "registry": "docker.io",
      "repository": "postgres",
      "vulnerabilities": {
        "CVE-2024-1234": {
          "severity": "high",
          "package": "postgresql",
          "version": "13.3",
          "fixed_version": "13.4",
          "description": "SQL injection vulnerability"
        }
      }
    }
  }'
```

### Upload File

```bash
curl -X POST http://localhost:8000/api/v1/ingest/file \
  -F "file=@/path/to/document.pdf" \
  -F 'metadata={"title": "My Document", "tags": ["important"]}'
```

---

## Running Validation

### 1. Upload Test Cases

```bash
curl -X POST http://localhost:8000/api/v1/validation/test-cases/upload \
  -F "file=@backend/validation/test_cases.json"
```

### 2. Run Validation

```bash
curl -X POST http://localhost:8000/api/v1/validation/run
```

**Response:**
```json
{
  "run_id": "run-123",
  "status": "completed",
  "test_count": 10,
  "executed_count": 10,
  "timestamp": "2024-01-15T10:30:00Z",
  "aggregate_metrics": {
    "mean_precision": 0.85,
    "mean_recall": 0.78,
    "mean_f1": 0.81,
    "mean_ndcg": 0.89,
    "mean_mrr": 0.92,
    "mean_map": 0.87
  }
}
```

### 3. View Dashboard

```bash
curl http://localhost:8000/api/v1/validation/dashboard
```

---

## Using Python SDK

### Ingest Container

```python
import asyncio
from backend.api.routes.ingestion import IngestDocumentRequest, IngestionSource
from backend.knowledge.ingestion.pipeline import IngestionPipeline

async def ingest_example():
    # Via API (recommended)
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/ingest",
            json={
                "source": "container",
                "container_metadata": {
                    "image_id": "sha256:abc123...",
                    "image_tag": "v1.0.0",
                    "registry": "docker.io",
                    "repository": "nginx"
                }
            }
        )
        print(response.json())

asyncio.run(ingest_example())
```

### Query Container Artifacts

```python
from backend.knowledge.graph.manager import graph_manager

async def query_containers():
    artifacts = await graph_manager.query_container_artifacts(
        registry="docker.io",
        limit=10
    )
    for artifact in artifacts:
        print(f"{artifact['repository']}:{artifact['tag']}")
        print(f"  Vulnerabilities: {len(artifact['vulnerabilities'])}")
        print(f"  SBOMs: {artifact['sboms']}")

asyncio.run(query_containers())
```

### Run Validation

```python
from backend.validation.harness import ValidationHarness

async def validate():
    harness = ValidationHarness()
    harness.load_test_cases_from_file("backend/validation/test_cases.json")

    results = await harness.run_all_tests()

    print(f"Mean Precision: {results['aggregate_metrics']['mean_precision']:.3f}")
    print(f"Mean Recall: {results['aggregate_metrics']['mean_recall']:.3f}")
    print(f"Mean F1: {results['aggregate_metrics']['mean_f1']:.3f}")

asyncio.run(validate())
```

---

## Troubleshooting

### Ingestion Stuck in "processing"

**Check Temporal worker:**
```bash
# Verify worker is running
docker-compose logs temporal-worker

# Restart worker
docker-compose restart temporal-worker
```

### MongoDB Connection Error

**Check MongoDB:**
```bash
docker-compose logs mongodb

# Verify connection
mongosh mongodb://localhost:27017
```

### Neo4j Query Timeout

**Create indexes:**
```cypher
CREATE INDEX ON :ContainerImage(image_id);
CREATE INDEX ON :ContainerImage(repository);
CREATE INDEX ON :Document(id);
```

### Validation Returns No Results

**Check test cases:**
```bash
# Verify test cases file exists
cat backend/validation/test_cases.json

# Check that expected document IDs are valid
```

---

## Next Steps

1. **Read Documentation**:
   - [Ingestion Service](INGESTION_SERVICE.md)
   - [Container Artifacts](CONTAINER_ARTIFACTS.md)
   - [Validation Harness](VALIDATION_HARNESS.md)
   - [Implementation Summary](IMPLEMENTATION_SUMMARY.md)

2. **Integrate with CI/CD**:
   - See [scripts/ingest_container_example.py](../scripts/ingest_container_example.py)
   - Add to GitHub Actions workflow

3. **Set up Monitoring**:
   - Configure Prometheus metrics
   - Set up Grafana dashboards
   - Enable alerting

4. **Customize**:
   - Add custom test cases
   - Extend container schema
   - Implement custom metrics

---

## API Reference

Full API documentation available at:
**http://localhost:8000/docs**

Key endpoints:
- `POST /api/v1/ingest` - Ingest document/container
- `GET /api/v1/ingest/{task_id}` - Get task status
- `POST /api/v1/validation/run` - Run validation
- `GET /api/v1/validation/dashboard` - QA dashboard

---

## Support

- **GitHub Issues**: Report bugs and request features
- **Documentation**: See [docs/](.) directory
- **Examples**: See [scripts/](../scripts/) directory
