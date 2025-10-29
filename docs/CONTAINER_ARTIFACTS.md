# Container Artifacts Guide

## Overview

Container artifacts in TwinOps represent container images with rich metadata including image IDs, tags, SBOM pointers, vulnerability scans, and deployment information. This guide covers how to ingest, query, and manage container artifacts.

## Quick Start

### 1. Ingest a Container Artifact

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source": "container",
    "tags": ["production", "backend", "api"],
    "container_metadata": {
      "image_id": "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
      "image_tag": "v2.1.0",
      "registry": "gcr.io",
      "repository": "myorg/backend-api",
      "sbom_uri": "s3://my-bucket/sboms/backend-api-v2.1.0-spdx.json",
      "sbom_format": "spdx",
      "created_at": "2024-01-15T10:00:00Z",
      "size_bytes": 524288000,
      "architecture": "amd64",
      "os": "linux",
      "layers": [
        "sha256:abc123...",
        "sha256:def456...",
        "sha256:ghi789..."
      ],
      "labels": {
        "maintainer": "devops@myorg.com",
        "version": "2.1.0",
        "environment": "production"
      },
      "vulnerabilities": {
        "CVE-2024-1234": {
          "severity": "high",
          "package": "openssl",
          "version": "1.1.1",
          "fixed_version": "1.1.1k",
          "description": "Buffer overflow in OpenSSL"
        },
        "CVE-2024-5678": {
          "severity": "critical",
          "package": "glibc",
          "version": "2.31",
          "fixed_version": "2.31-5",
          "description": "Remote code execution"
        }
      }
    }
  }'
```

### 2. Query Container Artifacts

```python
from backend.knowledge.graph.manager import graph_manager

# Query by registry
artifacts = await graph_manager.query_container_artifacts(
    registry="gcr.io",
    limit=50
)

# Query specific image
artifacts = await graph_manager.query_container_artifacts(
    repository="myorg/backend-api",
    tag="v2.1.0"
)

for artifact in artifacts:
    print(f"Image: {artifact['repository']}:{artifact['tag']}")
    print(f"Vulnerabilities: {len(artifact['vulnerabilities'])}")
    print(f"SBOMs: {artifact['sboms']}")
```

### 3. Query via Orchestration Router

```python
from backend.orchestration.router import OrchestrationRouter

router = OrchestrationRouter()
response = await router.route(
    session_id="test-session",
    user_id="user-123",
    text="Which containers have critical vulnerabilities in production?"
)

print(response['answer'])
for doc in response['documents']:
    print(f"- {doc['title']} (score: {doc['score']})")
```

---

## Schema Details

### Required Fields

- **image_id**: SHA256 digest (format: `sha256:...`, 71 chars)
- **image_tag**: Tag name (e.g., `v1.0.0`, `latest`)
- **registry**: Registry URL (e.g., `gcr.io`, `docker.io`)
- **repository**: Repository name (e.g., `myorg/backend-api`)

### Optional Fields

- **sbom_uri**: URI to SBOM document
- **sbom_format**: `spdx` or `cyclonedx`
- **created_at**: ISO 8601 timestamp
- **size_bytes**: Image size in bytes
- **architecture**: CPU architecture (`amd64`, `arm64`)
- **os**: Operating system (`linux`, `windows`)
- **layers**: List of layer digests
- **labels**: Key-value pairs
- **env_vars**: Environment variables
- **vulnerabilities**: CVE dictionary

---

## Neo4j Graph Schema

### Nodes

#### ContainerImage

```cypher
(:ContainerImage {
  image_id: "sha256:...",
  tag: "v1.0.0",
  repository: "myorg/backend-api",
  artifact_uri: "s3://...",
  version: "v1.0.0",
  base_image: "ubuntu:20.04",
  runtime: "docker",
  owner_team: "backend",
  labels: {...},
  build_info: {...},
  ingested_at: datetime()
})
```

#### SBOM

```cypher
(:SBOM {
  sbom_id: "sbom-sha256:...",
  uri: "s3://...",
  format: "spdx",
  version: "1.0",
  created_at: datetime()
})
```

#### Vulnerability

```cypher
(:Vulnerability {
  cve_id: "CVE-2024-1234",
  severity: "critical",
  package: "openssl",
  version: "1.1.1",
  fixed_version: "1.1.1k",
  description: "...",
  updated_at: datetime()
})
```

### Relationships

```cypher
// Container has SBOM
(:ContainerImage)-[:HAS_SBOM]->(:SBOM)
(:SBOM)-[:DESCRIBES]->(:ContainerImage)

// Container has vulnerabilities
(:ContainerImage)-[:HAS_VULNERABILITY {severity, detected_at}]->(:Vulnerability)
(:Vulnerability)-[:AFFECTS]->(:ContainerImage)

// Container documented
(:ContainerImage)-[:DOCUMENTED_IN]->(:Document)
(:Document)-[:DOCUMENTS]->(:ContainerImage)

// Service runs container
(:Service)-[:RUNS]->(:ContainerImage)
(:ContainerImage)-[:DEPLOYED_IN]->(:Service)

// Team ownership
(:Team)-[:OWNS]->(:ContainerImage)
(:ContainerImage)-[:OWNED_BY]->(:Team)
```

---

## Query Examples

### Find Containers with Critical Vulnerabilities

```cypher
MATCH (img:ContainerImage)-[rel:HAS_VULNERABILITY]->(vuln:Vulnerability)
WHERE vuln.severity = 'critical'
RETURN img.repository, img.tag, vuln.cve_id, vuln.package
ORDER BY vuln.severity DESC
```

### Find Containers Without SBOMs

```cypher
MATCH (img:ContainerImage)
WHERE NOT (img)-[:HAS_SBOM]->(:SBOM)
RETURN img.repository, img.tag, img.ingested_at
```

### Find All Versions of a Container

```cypher
MATCH (img:ContainerImage)
WHERE img.repository = 'myorg/backend-api'
RETURN img.tag, img.created_at, img.size_bytes
ORDER BY img.created_at DESC
```

### Find Containers by Team

```cypher
MATCH (team:Team {name: 'backend'})-[:OWNS]->(img:ContainerImage)
RETURN img.repository, img.tag, img.labels
```

### Impact Analysis: Services Affected by Vulnerability

```cypher
MATCH (vuln:Vulnerability {cve_id: 'CVE-2024-1234'})<-[:HAS_VULNERABILITY]-(img:ContainerImage)<-[:RUNS]-(svc:Service)
RETURN svc.name, svc.namespace, svc.cluster, img.repository, img.tag
```

---

## SBOM Integration

### Supported Formats

1. **SPDX** (Software Package Data Exchange)
2. **CycloneDX**

### SBOM Storage

SBOMs are stored separately in object storage and referenced via URI:

```python
from backend.knowledge.ingestion.container_storage import ContainerArtifactStorage

storage = ContainerArtifactStorage()

# Store SBOM separately
uris = await storage.store_artifact(
    artifact_id="artifact-123",
    container_metadata={...},
    sbom_content=sbom_json_bytes
)

# Retrieve SBOM
sbom_bytes = await storage.retrieve_sbom("artifact-123")
```

### Generating SBOMs

Use tools like:

- **Syft**: `syft packages docker:myorg/backend-api:v1.0.0 -o spdx-json`
- **Trivy**: `trivy image --format spdx-json myorg/backend-api:v1.0.0`
- **Grype**: `grype myorg/backend-api:v1.0.0 -o cyclonedx-json`

---

## Vulnerability Scanning

### Integrating Scan Results

```python
# Run vulnerability scan
scan_results = run_trivy_scan("myorg/backend-api:v1.0.0")

# Format vulnerabilities
vulnerabilities = {
    vuln["VulnerabilityID"]: {
        "severity": vuln["Severity"].lower(),
        "package": vuln["PkgName"],
        "version": vuln["InstalledVersion"],
        "fixed_version": vuln.get("FixedVersion"),
        "description": vuln["Description"]
    }
    for vuln in scan_results["Results"][0]["Vulnerabilities"]
}

# Ingest with vulnerabilities
await ingest_container(
    image_id="sha256:...",
    vulnerabilities=vulnerabilities
)
```

### Automated Scanning Pipeline

```bash
#!/bin/bash
# scan-and-ingest.sh

IMAGE=$1

# Scan with Trivy
trivy image --format json $IMAGE > scan.json

# Generate SBOM
syft packages docker:$IMAGE -o spdx-json > sbom.json

# Upload SBOM to S3
aws s3 cp sbom.json s3://my-bucket/sboms/${IMAGE//\//-}.json
SBOM_URI="s3://my-bucket/sboms/${IMAGE//\//-}.json"

# Parse scan results and ingest
python scripts/ingest_container.py \
  --image $IMAGE \
  --scan-results scan.json \
  --sbom-uri $SBOM_URI
```

---

## CI/CD Integration

### GitHub Actions

```yaml
name: Container Scan & Ingest

on:
  push:
    tags:
      - 'v*'

jobs:
  scan-ingest:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v2

      - name: Build image
        run: docker build -t myorg/backend-api:${{ github.ref_name }} .

      - name: Scan with Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: myorg/backend-api:${{ github.ref_name }}
          format: json
          output: scan.json

      - name: Generate SBOM
        run: |
          syft packages docker:myorg/backend-api:${{ github.ref_name }} -o spdx-json > sbom.json

      - name: Upload SBOM to S3
        run: |
          aws s3 cp sbom.json s3://${{ secrets.S3_BUCKET }}/sboms/backend-api-${{ github.ref_name }}.json

      - name: Ingest to TwinOps
        run: |
          python scripts/ingest_container.py \
            --api-url ${{ secrets.TWINOPS_API_URL }} \
            --image myorg/backend-api:${{ github.ref_name }} \
            --scan-results scan.json \
            --sbom-uri s3://${{ secrets.S3_BUCKET }}/sboms/backend-api-${{ github.ref_name }}.json
```

---

## Use Cases

### 1. Vulnerability Management

Query containers with specific vulnerabilities:

```
"Which containers are affected by CVE-2024-1234?"
"Show me all critical vulnerabilities in production"
"What's the remediation for vulnerabilities in the auth-service?"
```

### 2. Compliance Auditing

Track SBOM coverage:

```
"Which containers are missing SBOMs?"
"Generate a compliance report for containers in prod"
"Show me containers without vulnerability scans"
```

### 3. Dependency Tracking

Analyze dependencies across containers:

```
"Which containers use OpenSSL version 1.1.1?"
"Show me all containers with outdated dependencies"
"What's the dependency tree for the backend-api?"
```

### 4. Impact Analysis

Assess impact of vulnerabilities:

```
"Which services will be affected if I patch CVE-2024-1234?"
"Show me the blast radius of the glibc vulnerability"
"What's the priority order for patching these vulnerabilities?"
```

### 5. Version Management

Track container versions:

```
"What's the latest version of the backend-api?"
"Show me the changelog between v1.0.0 and v2.0.0"
"Which versions are deployed in each environment?"
```

---

## Best Practices

1. **Always Include SBOMs**: Generate and store SBOMs for all container images
2. **Automated Scanning**: Integrate vulnerability scanning into CI/CD
3. **Tag Immutability**: Use digest-based references for production deployments
4. **Regular Updates**: Re-scan containers periodically for new vulnerabilities
5. **Team Ownership**: Tag containers with owning team for accountability
6. **Environment Labels**: Use labels to indicate environment (dev, staging, prod)
7. **Retention Policies**: Archive old container versions after deprecation
8. **Access Control**: Restrict who can ingest production container metadata

---

## Monitoring & Alerts

### Prometheus Metrics

```prometheus
# Container ingestion rate
rate(container_ingestions_total[5m])

# Containers with critical vulnerabilities
container_vulnerabilities_total{severity="critical"}

# SBOM coverage
container_sbom_coverage_ratio
```

### Alert Rules

```yaml
groups:
  - name: container_alerts
    rules:
      - alert: CriticalVulnerabilityDetected
        expr: container_vulnerabilities_total{severity="critical"} > 0
        annotations:
          summary: "Critical vulnerability detected in {{ $labels.repository }}"

      - alert: MissingSBOM
        expr: container_sbom_coverage_ratio < 0.95
        annotations:
          summary: "SBOM coverage below 95%"
```

---

## Troubleshooting

### Invalid Image ID Format

**Error**: `image_id must be a valid SHA256 digest`

**Solution**: Ensure format is `sha256:` followed by 64 hex characters

### SBOM Not Found

**Error**: SBOM retrieval returns None

**Solution**:
- Check SBOM URI is correct
- Verify S3/GCS permissions
- Ensure SBOM was uploaded before ingestion

### Neo4j Query Timeout

**Solution**:
- Add indexes: `CREATE INDEX ON :ContainerImage(repository)`
- Limit result size
- Use APOC procedures for complex traversals

---

## Future Enhancements

1. **SBOM Parsing**: Extract detailed dependency information from SBOM documents
2. **License Compliance**: Track software licenses from SBOMs
3. **Drift Detection**: Detect runtime vs. image configuration drift
4. **Policy Enforcement**: Block ingestion of containers with critical vulnerabilities
5. **Cost Tracking**: Link container usage to cloud costs
6. **Provenance**: Track build provenance and signatures (SLSA)
