"""Query processing, digital twin, workflow, and delegation endpoints."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator

# Optional dependency for persistence typing
from motor.motor_asyncio import AsyncIOMotorCollection  # type: ignore

from backend.api.dependencies import get_current_user, get_db
from backend.core.database import DatabaseManager
from backend.core.exceptions import DelegationFailureError, KnowledgeNotFoundError
from backend.core.security import SecurityManager
from backend.knowledge.retrieval.citations import Citation
from backend.knowledge.retrieval.feedback import FeedbackSignal, FeedbackManager
from backend.knowledge.retrieval.graph_rag import GraphRAGEngine, RetrievalSummary, create_graph_rag_engine
from backend.knowledge.retrieval.offline import (
    FALLBACK_KNOWLEDGE_BASE,
    InMemoryGraphProvider,
    InMemoryTextRetriever,
    LocalEmbeddingGenerator,
    seed_vector_store,
)
from backend.knowledge.retrieval.ranker import HybridRanker
from backend.knowledge.vector.search import VectorSearchService
from backend.models import (
    IncidentInput,
    IncidentResult,
    Person,
    Priority,
    Query,
    Resource,
    Role,
    SeverityLevel,
    User,
)
from backend.utils.audit import audit_log
from backend.utils.monitoring import MonitoringService
from backend.workflows.activities import (
    ActivitiesContext,
    assess_severity,
    create_jira_ticket,
    execute_runbook,
    page_on_call_engineer,
    schedule_postmortem,
)
from backend.workflows.delegation import DelegationManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


# ---------------------------------------------------------------------------
# Support services and test data
# ---------------------------------------------------------------------------


class ModuleAuditLogger:
    async def log_access_attempt(self, user: User, resource: Resource, granted: bool) -> None:
        logger.info(
            "access_attempt user=%s resource=%s granted=%s",
            user.id,
            resource.id,
            granted,
        )

    async def log(self, payload: Dict[str, Any]) -> None:
        logger.debug("audit_log %s", payload)


class AllowAllRBAC:
    async def has_access(self, role: str, resource: Resource) -> bool:
        return True


class AllowAllABAC:
    async def evaluate(self, attributes: Dict[str, Any], resource_attributes: Dict[str, Any]) -> bool:
        return True


class SimpleEncryptionService:
    async def encrypt(self, value: Any) -> Any:
        if value is None:
            return None
        return f"enc::{value}"


class AuditContext(BaseModel):
    audit_logger: ModuleAuditLogger


def get_audit_context() -> AuditContext:
    return AuditContext(audit_logger=audit_logger)


audit_logger = ModuleAuditLogger()
monitoring_service = MonitoringService()
embedding_generator = LocalEmbeddingGenerator()
vector_service = VectorSearchService()
KNOWLEDGE_BASE = list(FALLBACK_KNOWLEDGE_BASE)
graph_provider = InMemoryGraphProvider(KNOWLEDGE_BASE)
text_retriever = InMemoryTextRetriever(KNOWLEDGE_BASE)
ranker = HybridRanker()
feedback_manager = FeedbackManager()

# Seed fallback vector store
seed_vector_store(vector_service, embedding_generator, KNOWLEDGE_BASE)


graph_rag_engine: GraphRAGEngine = create_graph_rag_engine(
    graph_provider=graph_provider,
    vector_search=vector_service,
    embedding_generator=embedding_generator,  # type: ignore[arg-type]
    text_retriever=text_retriever,
    ranker=ranker,
    weights={"graph": 0.4, "vector": 0.45, "text": 0.15},
    feedback_manager=feedback_manager,
)

security_manager = SecurityManager(
    rbac_service=AllowAllRBAC(),
    abac_service=AllowAllABAC(),
    audit_logger=audit_logger,
    encryption_service=SimpleEncryptionService(),
    pii_fields=["email", "phone"],
)

# ---------------------------------------------------------------------------
# Delegation scaffolding
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.utcnow()


DEFAULT_ROLES: Dict[str, Role] = {
    "infra_lead": Role(
        id="infra_lead",
        name="Infrastructure Lead",
        department="Platform",
        level="lead",
        responsibilities=["Owns AWS infrastructure", "Maintains runbooks"],
        required_skills=["aws", "terraform", "incident response"],
        delegation_chain=["sre_backup", "platform_manager"],
        knowledge_domains=["infrastructure", "aws"],
        created_at=_now(),
        updated_at=_now(),
        is_active=True,
        metadata={"manager_id": "platform_manager"},
    ),
    "sre_backup": Role(
        id="sre_backup",
        name="SRE Backup",
        department="Platform",
        level="senior",
        responsibilities=["Secondary on-call", "Coordinates with infra lead"],
        required_skills=["aws", "kubernetes"],
        delegation_chain=["platform_manager"],
        knowledge_domains=["infrastructure", "observability"],
        created_at=_now(),
        updated_at=_now(),
        is_active=True,
        metadata={"manager_id": "platform_manager"},
    ),
    "platform_manager": Role(
        id="platform_manager",
        name="Platform Engineering Manager",
        department="Platform",
        level="manager",
        responsibilities=["Escalation point", "Resource planning"],
        required_skills=["leadership", "aws"],
        delegation_chain=[],
        knowledge_domains=["management"],
        created_at=_now(),
        updated_at=_now(),
        is_active=True,
        metadata={"manager_id": "cto"},
    ),
}

ROLE_AVAILABILITY = {"infra_lead": False, "sre_backup": True, "platform_manager": True}


class InMemoryAvailabilityService:
    async def is_available(self, role: Role) -> bool:
        return ROLE_AVAILABILITY.get(role.id, True)

    async def resolve_person(self, role: Role) -> Optional[Person]:
        return None


class InMemoryGraphClient:
    async def fetch_delegates(
        self,
        role_id: str,
        responsibility: Optional[str],
        *,
        limit: int,
    ) -> List[Dict[str, Any]]:
        role = DEFAULT_ROLES.get(role_id)
        chain = role.delegation_chain if role else []
        delegates: List[Dict[str, Any]] = []
        for candidate in chain[:limit]:
            delegates.append({"role_id": candidate, "availability": "available", "person_id": None, "hops": 1})
        return delegates


class InMemoryRoleRepository:
    async def get_role(self, role_id: str) -> Role:
        try:
            return DEFAULT_ROLES[role_id]
        except KeyError as exc:
            raise DelegationFailureError(
                error_code="ROLE_NOT_FOUND",
                message=f"Role '{role_id}' not found",
            ) from exc

    async def get_roles(self, role_ids: Sequence[str]) -> List[Role]:
        roles: List[Role] = []
        for role_id in role_ids:
            if role_id in DEFAULT_ROLES:
                roles.append(DEFAULT_ROLES[role_id])
        return roles


class InMemoryEscalationService:
    async def escalate(self, current_role: Role) -> Role:
        manager_id = current_role.metadata.get("manager_id")
        if manager_id and manager_id in DEFAULT_ROLES:
            return DEFAULT_ROLES[manager_id]
        return current_role


class InMemorySkillRouter:
    async def find_best_match(self, required_skills: Sequence[str]) -> Role:
        best_role: Optional[Role] = None
        best_score = -1
        for role in DEFAULT_ROLES.values():
            score = len(set(required_skills) & set(role.required_skills))
            if score > best_score:
                best_score = score
                best_role = role
        if best_role:
            return best_role
        raise DelegationFailureError(
            error_code="DELEGATION_FAILED",
            message="No suitable person found for delegation",
            details={"required_skills": list(required_skills)},
        )


delegation_manager = DelegationManager(
    availability_service=InMemoryAvailabilityService(),
    graph_client=InMemoryGraphClient(),
    role_repository=InMemoryRoleRepository(),
    escalation_service=InMemoryEscalationService(),
    skill_router=InMemorySkillRouter(),
)

# ---------------------------------------------------------------------------
# Workflow facilitator
# ---------------------------------------------------------------------------


class WorkflowExecutor:
    def __init__(self) -> None:
        self.activities = ActivitiesContext()

    async def execute_incident(self, incident: IncidentInput) -> IncidentResult:
        severity = await assess_severity(incident)

        acknowledgements: List[str] = []
        escalated_to: Optional[str] = None

        if severity >= SeverityLevel.HIGH:
            ack = await page_on_call_engineer(incident)
            acknowledgements.append(ack)
            escalated_to = ack

        ticket_id = await create_jira_ticket(incident)

        if incident.has_runbook and incident.runbook_id:
            await execute_runbook(incident.runbook_id)

        postmortem_id = await schedule_postmortem(incident)
        acknowledgements.append(postmortem_id)

        return IncidentResult(
            ticket_id=ticket_id,
            status="handled",
            acknowledgements=acknowledgements,
            escalated_to=escalated_to,
        )


workflow_executor = WorkflowExecutor()

# ---------------------------------------------------------------------------
# Snapshot persistence helpers
# ---------------------------------------------------------------------------


def _snapshot_collection() -> AsyncIOMotorCollection:
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Snapshot persistence store is unavailable. Ensure MongoDB is configured.",
        )
    return mongodb["twinops"]["twin_snapshots"]


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.fromtimestamp(0)
    return datetime.utcnow()


def _decode_snapshot(document: Dict[str, Any]) -> SnapshotResponse:
    knowledge_payload = document.get("knowledge", []) or []
    knowledge = [TwinKnowledgeModel.model_validate(item) for item in knowledge_payload]
    return SnapshotResponse(
        snapshot_id=str(document.get("_id")),
        role_id=str(document.get("role_id")),
        created_at=_coerce_datetime(document.get("created_at")),
        metadata=dict(document.get("metadata", {})),
        knowledge=knowledge,
    )

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CitationModel(BaseModel):
    source_id: str
    document_name: str
    page_number: Optional[int] = None
    confidence_score: float
    timestamp: datetime
    direct_link: str

    @classmethod
    def from_dataclass(cls, citation: Citation) -> "CitationModel":
        return cls(
            source_id=citation.source_id,
            document_name=citation.document_name,
            page_number=citation.page_number,
            confidence_score=citation.confidence_score,
            timestamp=citation.timestamp,
            direct_link=citation.direct_link,
        )


class QueryDocumentModel(BaseModel):
    document_id: str
    score: float
    confidence: float
    component_scores: Dict[str, float]
    metadata: Dict[str, Any]
    citations: List[CitationModel]


class QueryMetricsModel(BaseModel):
    precision: float
    recall: float


class QueryInput(BaseModel):
    query: str
    top_k: int = Field(5, ge=1, le=20)
    filters: Dict[str, Any] = Field(default_factory=dict)

    @validator("query")
    def validate_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Query cannot be empty")
        return value


class ProcessQueryResponse(BaseModel):
    query_id: str
    results: List[QueryDocumentModel]
    metrics: QueryMetricsModel
    source_count: int
    weights: Dict[str, float]
    experiments: Optional[List[Dict[str, Any]]] = None


class FeedbackRequest(BaseModel):
    query: str
    document_id: str
    helpful: bool
    score: float = Field(..., ge=0.0, le=1.0)
    channel: str = Field("ui", max_length=32)
    component_scores: Optional[Dict[str, float]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TwinKnowledgeModel(BaseModel):
    document_id: str
    title: str
    summary: str
    citations: List[CitationModel]


class TwinDetailsResponse(BaseModel):
    role: Role
    knowledge: List[TwinKnowledgeModel]
    last_updated: datetime


class SnapshotRequest(BaseModel):
    note: Optional[str] = None


class SnapshotResponse(BaseModel):
    snapshot_id: str
    role_id: str
    created_at: datetime
    metadata: Dict[str, Any]
    knowledge: List[TwinKnowledgeModel] = Field(default_factory=list)


class WorkflowInput(BaseModel):
    workflow_name: str = Field(..., example="incident_response")
    payload: Dict[str, Any] = Field(default_factory=dict)


class WorkflowExecutionResponse(BaseModel):
    run_id: str
    status: str
    metadata: Dict[str, Any]


class DelegationInput(BaseModel):
    query: str
    current_role_id: str
    priority: Priority
    required_skills: List[str] = Field(default_factory=list)


class DelegationResponse(BaseModel):
    assigned_role: Role
    reason: str


# ---------------------------------------------------------------------------
# Endpoint implementations
# ---------------------------------------------------------------------------


def _convert_summary(summary: RetrievalSummary) -> ProcessQueryResponse:
    documents = [
        QueryDocumentModel(
            document_id=doc.document_id,
            score=doc.score,
            confidence=doc.confidence,
            component_scores=doc.component_scores,
            metadata=doc.metadata,
            citations=[CitationModel.from_dataclass(citation) for citation in doc.citations],
        )
        for doc in summary.documents
    ]
    metrics = QueryMetricsModel(precision=summary.precision, recall=summary.recall)
    experiments = None
    if summary.experiments:
        experiments = [
            {
                "weights": result.weights,
                "score": result.score,
                "coverage": result.coverage,
                "diversity": result.diversity,
                "top_documents": result.top_documents,
            }
            for result in summary.experiments
        ]
    return ProcessQueryResponse(
        query_id=str(uuid.uuid4()),
        results=documents,
        metrics=metrics,
        source_count=len(summary.sources),
        weights=summary.weights,
        experiments=experiments,
    )


@router.post(
    "/v1/query",
    response_model=ProcessQueryResponse,
    status_code=status.HTTP_200_OK,
)
@audit_log
async def process_query(
    payload: QueryInput,
    current_user: User = Depends(get_current_user),
    db: DatabaseManager = Depends(get_db),
    audit_ctx: AuditContext = Depends(get_audit_context),
) -> ProcessQueryResponse:
    del db  # Currently unused, placeholder for future DB interactions.
    del audit_ctx  # The audit decorator consumes this dependency.

    resource = Resource(id="knowledge-base", type="knowledge", attributes=payload.filters, classification=1)
    if not await security_manager.check_access(current_user, resource):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await monitoring_service.track_query(query_id=str(uuid.uuid4()))

    priority_value = payload.filters.get("priority", Priority.MEDIUM)
    if isinstance(priority_value, str):
        try:
            priority_value = Priority(priority_value)
        except ValueError:
            priority_value = Priority.MEDIUM

    skills_value = payload.filters.get("skills", [])
    if isinstance(skills_value, str):
        skills_value = [skills_value]

    query_model = Query(
        id=str(uuid.uuid4()),
        content=payload.query,
        created_at=datetime.utcnow(),
        priority=priority_value,
        required_skills=list(skills_value),
        context=payload.filters,
    )

    try:
        summary = await graph_rag_engine.retrieve(payload.query, top_k=payload.top_k)
    except KnowledgeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc

    return _convert_summary(summary)


@router.post(
    "/v1/query/feedback",
    status_code=status.HTTP_202_ACCEPTED,
)
@audit_log
async def submit_feedback(
    payload: FeedbackRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    metadata = dict(payload.metadata)
    if payload.component_scores:
        metadata.setdefault("component_scores", payload.component_scores)
    metadata.setdefault("channel", payload.channel)

    signal = FeedbackSignal(
        query=payload.query,
        document_id=payload.document_id,
        user_id=current_user.id,
        helpful=payload.helpful,
        score=payload.score,
        channel=payload.channel,
        metadata=metadata,
    )

    await graph_rag_engine.record_feedback(signal)
    return {"status": "accepted"}


@router.get(
    "/v1/twins/{role_id}",
    response_model=TwinDetailsResponse,
    status_code=status.HTTP_200_OK,
)
@audit_log
async def get_twin_details(role_id: str, audit_ctx: AuditContext = Depends(get_audit_context)) -> TwinDetailsResponse:
    del audit_ctx
    role = DEFAULT_ROLES.get(role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    summary = await graph_rag_engine.retrieve(role.name, top_k=3)
    knowledge = [
        TwinKnowledgeModel(
            document_id=doc.document_id,
            title=doc.metadata.get("title", ""),
            summary=doc.metadata.get("summary", ""),
            citations=[CitationModel.from_dataclass(citation) for citation in doc.citations],
        )
        for doc in summary.documents
    ]

    return TwinDetailsResponse(role=role, knowledge=knowledge, last_updated=datetime.utcnow())


@router.post(
    "/v1/twins/{role_id}/snapshot",
    response_model=SnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
@audit_log
async def create_twin_snapshot(
    role_id: str,
    payload: SnapshotRequest,
    audit_ctx: AuditContext = Depends(get_audit_context),
) -> SnapshotResponse:
    del audit_ctx
    if role_id not in DEFAULT_ROLES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    collection = _snapshot_collection()
    created_at = datetime.utcnow()

    knowledge: List[TwinKnowledgeModel] = []
    try:
        summary = await graph_rag_engine.retrieve(DEFAULT_ROLES[role_id].name, top_k=3)
    except KnowledgeNotFoundError:
        summary = None

    if summary:
        knowledge = [
            TwinKnowledgeModel(
                document_id=doc.document_id,
                title=doc.metadata.get("title", ""),
                summary=doc.metadata.get("summary") or doc.metadata.get("chunk", ""),
                citations=[CitationModel.from_dataclass(citation) for citation in doc.citations],
            )
            for doc in summary.documents
        ]

    snapshot = SnapshotResponse(
        snapshot_id=str(uuid.uuid4()),
        role_id=role_id,
        created_at=created_at,
        metadata={
            "note": payload.note,
            "captured_documents": [item.document_id for item in knowledge],
        },
        knowledge=knowledge,
    )

    await collection.insert_one(
        {
            "_id": snapshot.snapshot_id,
            "role_id": snapshot.role_id,
            "created_at": snapshot.created_at,
            "metadata": snapshot.metadata,
            "knowledge": [item.model_dump(mode="python") for item in snapshot.knowledge],
        }
    )

    return snapshot


@router.get(
    "/v1/twins/{role_id}/snapshot",
    response_model=List[SnapshotResponse],
    status_code=status.HTTP_200_OK,
)
@audit_log
async def list_twin_snapshots(
    role_id: str,
    audit_ctx: AuditContext = Depends(get_audit_context),
) -> List[SnapshotResponse]:
    del audit_ctx
    if role_id not in DEFAULT_ROLES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")

    collection = _snapshot_collection()
    cursor = collection.find({"role_id": role_id}).sort("created_at", -1)
    documents = await cursor.to_list(length=200)
    return [_decode_snapshot(document) for document in documents]


@router.post(
    "/v1/workflows/execute",
    response_model=WorkflowExecutionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@audit_log
async def execute_workflow(
    payload: WorkflowInput,
    audit_ctx: AuditContext = Depends(get_audit_context),
) -> WorkflowExecutionResponse:
    del audit_ctx
    if payload.workflow_name != "incident_response":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported workflow")

    incident = IncidentInput(**payload.payload)
    result = await workflow_executor.execute_incident(incident)
    return WorkflowExecutionResponse(
        run_id=str(uuid.uuid4()),
        status=result.status,
        metadata={"ticket_id": result.ticket_id, "acknowledgements": result.acknowledgements},
    )


@router.post(
    "/v1/delegation/route",
    response_model=DelegationResponse,
    status_code=status.HTTP_200_OK,
)
@audit_log
async def route_delegation(
    delegation: DelegationInput,
    audit_ctx: AuditContext = Depends(get_audit_context),
) -> DelegationResponse:
    del audit_ctx
    try:
        current_role = await InMemoryRoleRepository().get_role(delegation.current_role_id)
        query = Query(
            id=str(uuid.uuid4()),
            content=delegation.query,
            created_at=datetime.utcnow(),
            priority=delegation.priority,
            required_skills=delegation.required_skills,
            context={},
        )
        assignee = await delegation_manager.route_query(query, current_role)
    except DelegationFailureError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message) from exc

    reason = "Delegated via availability chain" if assignee.id != delegation.current_role_id else "Primary role available"
    return DelegationResponse(assigned_role=assignee, reason=reason)
