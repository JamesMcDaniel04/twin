# TwinOps

> **Production-grade digital twin platform for operational continuity through Slack**

TwinOps creates intelligent role-based digital twins that preserve institutional knowledge and enable workflow automation. When subject-matter experts are unavailable, TwinOps provides accurate, source-cited responses and executes automated workflows through a natural Slack interface.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## Key Features

- **Graph-RAG Hybrid Retrieval**: Combines Neo4j graph traversal with vector similarity search for context-aware responses
- **Source Traceability**: Every response includes citations to original documents with confidence scores
- **Slack-Native Interface**: All interactions through `/twin`, `/delegate`, `/snapshot` commands and conversational AI
- **Automated Workflows**: Temporal-based orchestration for incident response, releases, and onboarding
- **Smart Delegation**: Automatic routing based on availability, skills, and organizational hierarchy
- **Multi-Source Ingestion**: Processes documents from Slack, Google Drive, Confluence, GitHub, and Jira

---

## Architecture

TwinOps implements a 5-layer architecture designed for production scale:

### 1. Slack Bot Interface Layer
Primary user interaction via:
- `/twin` - Query digital twin knowledge
- `/delegate` - Route requests to available personnel
- `/snapshot` - Create point-in-time knowledge snapshots
- Conversational AI through @mentions
- Interactive Block Kit UIs for approvals and confirmations

### 2. Orchestration & Intelligence Layer
- Request routing and context management
- Session state tracking across conversations
- Graph-RAG query planning and execution
- Response synthesis with LLM (GPT-4 primary, Claude fallback)

### 3. Knowledge Processing Layer
- **Ingestion Pipeline**: Document parsing → entity extraction → semantic chunking → embedding generation
- **Graph-RAG Retrieval**: Hybrid search combining graph context + vector similarity + full-text search
- **Source Attribution**: Automatic citation generation with confidence scoring

### 4. Data Storage Layer
- **Neo4j**: Knowledge graph (roles, people, documents, relationships)
- **Pinecone**: Vector embeddings for semantic search
- **MongoDB**: Full document storage and metadata
- **Redis**: Session cache and rate limiting
- **Elasticsearch**: Full-text search index

### 5. Integration Layer
- **Slack**: Events, commands, interactive components
- **Jira**: Issue creation and updates
- **Google Workspace**: Drive, Calendar, Gmail
- **GitHub**: Code context and PR integration
- **Confluence**: Documentation sync

### Supporting Infrastructure
- **Temporal**: Workflow orchestration and state management
- **Kafka**: Event streaming and async processing
- **Prometheus + Grafana**: Metrics and monitoring
- **Jaeger**: Distributed tracing via OpenTelemetry

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Neo4j 5.x
- Pinecone account
- Slack workspace with bot permissions
- OpenAI API key

### 1. Clone and Setup Environment

```bash
git clone https://github.com/yourusername/twinops.git
cd twinops

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### 2. Configure Environment Variables

Edit `.env` and provide:
- Neo4j credentials
- Pinecone API key and index name
- Slack bot token and signing secret
- OpenAI API key
- Integration credentials (Jira, Google, GitHub)

See [.env.example](.env.example) for complete configuration details.

### 3. Start Infrastructure Services

```bash
# Start Neo4j, Redis, MongoDB, Elasticsearch
docker-compose up -d

# Verify services are running
docker-compose ps
```

### 4. Initialize Database Schema

```bash
# Run Neo4j graph schema migrations
python scripts/migrate.py

# (Optional) Seed with sample data
python scripts/seed.py
```

### 5. Start the Application

```bash
# Development mode with auto-reload
uvicorn backend.api.main:app --reload --port 8000

# Production mode
uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --workers 4
```

API will be available at `http://localhost:8000`

### 6. Start Temporal Worker (for workflows)

In a separate terminal:

```bash
python backend/workflows/worker.py
```

---

## Project Structure

```
twinops/
├── backend/                    # Backend application code
│   ├── api/                   # FastAPI routes and middleware
│   │   ├── routes/           # API endpoints (query, twin, workflow, admin)
│   │   └── middleware/       # Auth, logging, rate limiting
│   ├── core/                 # Core infrastructure
│   │   ├── config.py         # Configuration management
│   │   ├── database.py       # Database connections
│   │   └── security.py       # RBAC/ABAC security
│   ├── knowledge/            # Knowledge processing
│   │   ├── graph/           # Neo4j graph operations
│   │   ├── vector/          # Pinecone vector operations
│   │   ├── retrieval/       # Graph-RAG hybrid retrieval
│   │   └── ingestion/       # Document ingestion pipeline
│   ├── orchestration/        # Request routing and context
│   ├── integrations/         # External service connectors
│   │   └── slack/           # Slack bot implementation
│   ├── workflows/            # Temporal workflow definitions
│   │   └── templates/       # Pre-built workflow templates
│   ├── models/              # Pydantic data models
│   └── utils/               # Utilities (LLM, monitoring, audit)
│
├── frontend/                  # Admin web portal (React)
│   └── admin/
│
├── infrastructure/            # Infrastructure as code
│   ├── docker/               # Dockerfiles
│   ├── kubernetes/           # K8s manifests
│   └── terraform/            # AWS infrastructure
│
├── scripts/                   # Setup and maintenance scripts
│   ├── setup.py              # Initial setup
│   ├── migrate.py            # Database migrations
│   └── seed.py               # Sample data seeding
│
├── tests/                     # Test suite
│   ├── unit/
│   ├── integration/
│   └── e2e/
│
├── .env.example              # Environment template
├── requirements.txt          # Python dependencies
├── pyproject.toml           # Project configuration
└── docker-compose.yml       # Local development stack
```

---

## Usage Examples

### Query Digital Twin via Slack

```
/twin Who handles AWS infrastructure issues?
```

Response includes:
- Role information (SRE On-Call)
- Current person filling role
- Relevant documentation with citations
- Availability status

### Delegate a Task

```
/delegate Create Jira ticket for database performance investigation
```

TwinOps will:
1. Identify required skills (database, performance)
2. Find available person with matching skills
3. Create Jira ticket
4. Notify assignee via Slack

### Create Knowledge Snapshot

```
/snapshot Release-v2.3.4
```

Creates point-in-time snapshot of:
- Current role assignments
- Active workflows
- Relevant documentation state

---

## Development

### Running Tests

```bash
# All tests with coverage
pytest --cov=backend --cov-report=html

# Unit tests only
pytest tests/unit -v

# Integration tests
pytest tests/integration -v

# Specific test file
pytest tests/integration/test_graph_rag.py -v
```

### Code Quality

```bash
# Format code
black backend/ tests/
isort backend/ tests/

# Lint
flake8 backend/ tests/

# Type checking
mypy backend/
```

### Pre-commit Hooks

```bash
# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

---

## Deployment

### Docker

```bash
# Build image
docker build -f infrastructure/docker/Dockerfile.backend -t twinops-backend:latest .

# Run container
docker run -p 8000:8000 --env-file .env twinops-backend:latest
```

### Kubernetes

```bash
# Apply manifests
kubectl apply -f infrastructure/kubernetes/

# Check deployment status
kubectl get pods -n twinops
kubectl logs -f deployment/twinops-backend -n twinops
```

### AWS (Terraform)

```bash
cd infrastructure/terraform/aws
terraform init
terraform plan
terraform apply
```

---

## Performance Requirements

Production deployment must meet:

- **Response Time**: p95 < 3 seconds, p99 < 5 seconds
- **Throughput**: 10,000+ queries/hour
- **Concurrent Users**: 1,000+
- **Accuracy**: 95%+ query accuracy
- **Availability**: 99.9% uptime

---

## Monitoring

### Metrics (Prometheus)

- `queries_total` - Total queries processed
- `query_duration_seconds` - Query latency histogram
- `active_twins` - Number of active digital twins

Access Grafana dashboards at `http://localhost:3000`

### Tracing (Jaeger)

View distributed traces at `http://localhost:16686`

### Logs

Structured JSON logs with correlation IDs:

```bash
# View logs
docker-compose logs -f backend

# Filter by request ID
docker-compose logs backend | grep "request_id=abc123"
```

---

## Security

- **Authentication**: JWT tokens for API access
- **Authorization**: RBAC + ABAC for resource access
- **Data Classification**: Public, Internal, Confidential, Secret levels
- **Encryption**: Field-level encryption for PII
- **Audit Logging**: Complete audit trail of all operations
- **Rate Limiting**: Configurable per-user and global limits

---

## Telemetry Verification

TwinOps exports traces via OpenTelemetry. Configure exporters using environment variables:

```env
OTEL_EXPORTER_JAEGER_ENDPOINT=http://jaeger:14268/api/traces
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer your-token
```

Send a diagnostic span to confirm connectivity:

```bash
poetry run python scripts/verify_tracing.py
```

Look for the span named `telemetry_verification` in Jaeger/Tempo to verify ingestion.

---

## API Access Provisioning

Use the admin API to provision service credentials.

1. Authenticate as an admin (role `system`/`admin` or clearance ≥ 8).
2. Create a long-lived API key (value returned once):

```bash
curl -X POST http://localhost:8080/api/admin/api-keys \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{
        "name": "automation-bot",
        "email": "automation@twinops.local",
        "role": "service",
        "clearance_level": 6,
        "attributes": {"team": "automation"}
      }'
```

3. Issue a short-lived JWT:

```bash
curl -X POST http://localhost:8080/api/admin/jwt \
  -H "Authorization: X-API-Key <admin-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
        "subject": "cli-runner",
        "role": "service",
        "email": "cli@twinops.local",
        "clearance_level": 4,
        "expires_minutes": 120
      }'
```

API keys are persisted in MongoDB (`twinops.api_keys`) and can be listed or revoked via the same API.

---

## Seeding Delegation Graph

Populate Neo4j with roles, people, and delegation relationships for local testing:

```bash
poetry run python scripts/seed_roles.py
```

The seed job creates:

- `Role` nodes with `DELEGATES_TO` / `REPORTS_TO` links and responsibilities
- `Person` nodes with `HOLDS_ROLE` relations and availability metadata
- `Responsibility` nodes connected via `RESPONSIBLE_FOR`

Modify `scripts/seed_roles.py` to reflect your organisation before running in shared environments.

---

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

---

## License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.

---

## Support

- **Documentation**: [https://docs.twinops.io](https://docs.twinops.io)
- **Issues**: [GitHub Issues](https://github.com/yourusername/twinops/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/twinops/discussions)
- **Email**: support@twinops.io

---

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [Neo4j](https://neo4j.com/) - Graph database
- [Pinecone](https://www.pinecone.io/) - Vector database
- [Temporal](https://temporal.io/) - Workflow orchestration
- [Slack Bolt](https://slack.dev/bolt-python/) - Slack integration framework
