"""Delegation logic for TwinOps workflows backed by Neo4j relationships."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

from backend.core.database import database_manager
from backend.core.exceptions import DelegationFailureError
from backend.models.query import Query
from backend.models.role import Person, Role

logger = logging.getLogger(__name__)


class AvailabilityService(Protocol):
    async def is_available(self, role: Role) -> bool:
        ...

    async def resolve_person(self, role: Role) -> Optional[Person]:
        ...


class DelegationGraphClient(Protocol):
    async def fetch_delegates(
        self,
        role_id: str,
        responsibility: Optional[str],
        *,
        limit: int,
    ) -> List[Dict[str, Any]]:
        ...


class RoleRepository(Protocol):
    async def get_role(self, role_id: str) -> Role:
        ...

    async def get_roles(self, role_ids: Sequence[str]) -> List[Role]:
        ...


class EscalationService(Protocol):
    async def escalate(self, current_role: Role) -> Role:
        ...


class SkillRouter(Protocol):
    async def find_best_match(self, required_skills: Sequence[str]) -> Role:
        ...


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_native"):
        return value.to_native()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.utcnow()


class Neo4jDelegationGraphClient:
    async def fetch_delegates(
        self,
        role_id: str,
        responsibility: Optional[str],
        *,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        driver = database_manager.neo4j
        if driver is None:
            logger.debug("Neo4j driver unavailable; fallback to role-defined delegation chain.")
            return []

        cypher = """
        MATCH (current:Role {id: $role_id})
        OPTIONAL MATCH path = (current)-[:DELEGATES_TO|BACKS_UP*1..3]->(delegate:Role)
        WHERE coalesce(delegate.is_active, true)
        OPTIONAL MATCH (delegate)<-[:HOLDS_ROLE]-(person:Person)
        OPTIONAL MATCH (delegate)-[:RESPONSIBLE_FOR]->(resp:Responsibility)
        WITH DISTINCT delegate, person, length(path) AS hops, resp
        WHERE delegate IS NOT NULL
        RETURN delegate.id AS role_id,
               delegate.level AS level,
               hops AS hops,
               coalesce(person.availability_status, 'unknown') AS availability,
               person.id AS person_id,
               CASE WHEN resp.name = $responsibility THEN 0 ELSE 1 END AS responsibility_rank
        ORDER BY responsibility_rank ASC,
                 CASE availability WHEN 'available' THEN 0 WHEN 'online' THEN 1 WHEN 'busy' THEN 2 ELSE 3 END ASC,
                 hops ASC,
                 delegate.level ASC
        LIMIT $limit
        """

        async with driver.session() as session:
            result = await session.run(
                cypher,
                {
                    "role_id": role_id,
                    "responsibility": responsibility or "",
                    "limit": limit,
                },
            )
            records = await result.data()
        return records


class Neo4jRoleRepository:
    async def get_role(self, role_id: str) -> Role:
        roles = await self.get_roles([role_id])
        if not roles:
            raise DelegationFailureError(
                error_code="ROLE_NOT_FOUND",
                message=f"Role '{role_id}' was not found in the knowledge graph.",
            )
        return roles[0]

    async def get_roles(self, role_ids: Sequence[str]) -> List[Role]:
        if not role_ids:
            return []

        driver = database_manager.neo4j
        if driver is None:
            raise DelegationFailureError(
                error_code="GRAPH_UNAVAILABLE",
                message="Neo4j driver unavailable while resolving roles.",
            )

        cypher = """
        UNWIND $ids AS role_id
        MATCH (r:Role {id: role_id})
        OPTIONAL MATCH (r)-[:DELEGATES_TO]->(delegate:Role)
        WITH role_id, r, collect(delegate.id) AS delegation_chain
        RETURN role_id, r, delegation_chain
        """

        async with driver.session() as session:
            result = await session.run(cypher, {"ids": list(role_ids)})
            records = await result.data()

        role_map: Dict[str, Role] = {}
        for record in records:
            node = record.get("r")
            if node is None:
                continue
            data = dict(node)
            delegation_chain = [item for item in record.get("delegation_chain", []) if item]
            role_id = data.get("id") or record.get("role_id")
            if role_id is None:
                continue
            role_map[role_id] = Role(
                id=role_id,
                name=data.get("name", role_id.replace("_", " ").title()),
                department=data.get("department", "unknown"),
                level=data.get("level", "mid"),
                responsibilities=list(data.get("responsibilities", [])),
                required_skills=list(data.get("required_skills", [])),
                delegation_chain=list(data.get("delegation_chain", delegation_chain)),
                knowledge_domains=list(data.get("knowledge_domains", [])),
                created_at=_coerce_datetime(data.get("created_at")),
                updated_at=_coerce_datetime(data.get("updated_at")),
                is_active=bool(data.get("is_active", True)),
                metadata=dict(data.get("metadata", {})),
            )

        ordered: List[Role] = []
        for role_id in role_ids:
            role = role_map.get(role_id)
            if role:
                ordered.append(role)
        return ordered


class Neo4jAvailabilityService:
    AVAILABLE_STATES = {"available", "online"}

    async def is_available(self, role: Role) -> bool:
        driver = database_manager.neo4j
        if driver is None:
            return True

        cypher = """
        MATCH (r:Role {id: $role_id})<-[:HOLDS_ROLE]-(p:Person)
        RETURN p.availability_status AS status
        ORDER BY CASE status WHEN 'available' THEN 0 WHEN 'online' THEN 1 WHEN 'busy' THEN 2 ELSE 3 END
        LIMIT 1
        """

        async with driver.session() as session:
            result = await session.run(cypher, {"role_id": role.id})
            record = await result.single()

        status = record.get("status") if record else None
        if status is None:
            return True
        return status in self.AVAILABLE_STATES

    async def resolve_person(self, role: Role) -> Optional[Person]:
        driver = database_manager.neo4j
        if driver is None:
            return None

        cypher = """
        MATCH (r:Role {id: $role_id})<-[:HOLDS_ROLE]-(p:Person)
        RETURN p
        ORDER BY CASE p.availability_status WHEN 'available' THEN 0 WHEN 'online' THEN 1 WHEN 'busy' THEN 2 ELSE 3 END
        LIMIT 1
        """

        async with driver.session() as session:
            result = await session.run(cypher, {"role_id": role.id})
            record = await result.single()

        node = record.get("p") if record else None
        if node is None:
            return None
        data = dict(node)
        return Person(
            id=data.get("id", role.id),
            name=data.get("name", role.name),
            email=data.get("email", ""),
            slack_id=data.get("slack_id", ""),
            current_role_id=role.id,
            past_roles=list(data.get("past_roles", [])),
            skills=list(data.get("skills", [])),
            availability_status=data.get("availability_status", "unknown"),
            timezone=data.get("timezone", "UTC"),
            created_at=_coerce_datetime(data.get("created_at")),
        )


class Neo4jEscalationService:
    def __init__(self, role_repository: RoleRepository) -> None:
        self.role_repository = role_repository

    async def escalate(self, current_role: Role) -> Role:
        driver = database_manager.neo4j
        if driver is None:
            return current_role

        cypher = """
        MATCH (r:Role {id: $role_id})-[:REPORTS_TO]->(manager:Role)
        RETURN manager.id AS role_id
        ORDER BY manager.level DESC
        LIMIT 1
        """

        async with driver.session() as session:
            result = await session.run(cypher, {"role_id": current_role.id})
            record = await result.single()

        manager_id = record.get("role_id") if record else None
        if not manager_id:
            return current_role
        try:
            return await self.role_repository.get_role(manager_id)
        except DelegationFailureError:
            return current_role


class Neo4jSkillRouter:
    def __init__(self, role_repository: RoleRepository) -> None:
        self.role_repository = role_repository

    async def find_best_match(self, required_skills: Sequence[str]) -> Role:
        skills = [skill for skill in required_skills if skill]
        if not skills:
            raise DelegationFailureError(
                error_code="DELEGATION_FAILED",
                message="No skills provided for fallback delegation.",
            )

        driver = database_manager.neo4j
        if driver is None:
            raise DelegationFailureError(
                error_code="GRAPH_UNAVAILABLE",
                message="Neo4j driver unavailable while routing by skills.",
            )

        cypher = """
        MATCH (candidate:Role)
        WHERE candidate.is_active <> false
        WITH candidate, [skill IN coalesce(candidate.required_skills, []) WHERE skill IN $skills] AS overlap
        WHERE size(overlap) > 0
        RETURN candidate.id AS role_id, size(overlap) AS score
        ORDER BY score DESC, candidate.level ASC
        LIMIT 1
        """

        async with driver.session() as session:
            result = await session.run(cypher, {"skills": skills})
            record = await result.single()

        role_id = record.get("role_id") if record else None
        if not role_id:
            raise DelegationFailureError(
                error_code="DELEGATION_FAILED",
                message="No role matches the required skills in the graph.",
                details={"skills": list(skills)},
            )
        return await self.role_repository.get_role(role_id)


class DelegationManager:
    """Select appropriate delegate roles based on Neo4j relationships and availability."""

    def __init__(
        self,
        *,
        availability_service: Optional[AvailabilityService] = None,
        graph_client: Optional[DelegationGraphClient] = None,
        role_repository: Optional[RoleRepository] = None,
        escalation_service: Optional[EscalationService] = None,
        skill_router: Optional[SkillRouter] = None,
        fallback_chain: Optional[Iterable[str]] = None,
    ) -> None:
        self.graph_client = graph_client or Neo4jDelegationGraphClient()
        self.role_repository = role_repository or Neo4jRoleRepository()
        self.availability_service = availability_service or Neo4jAvailabilityService()
        self.escalation_service = escalation_service or Neo4jEscalationService(self.role_repository)
        self.skill_router = skill_router or Neo4jSkillRouter(self.role_repository)
        self.default_chain: List[str] = list(fallback_chain or ("incident_commander", "ops_lead", "sre_oncall"))

    async def select_delegate(
        self,
        role: Role,
        responsibility: Optional[str] = None,
        *,
        limit: int = 5,
        precomputed: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        records = precomputed or await self.graph_client.fetch_delegates(role.id, responsibility, limit=limit)
        ordered: List[str] = []
        for record in records:
            candidate_id = record.get("role_id")
            if candidate_id and candidate_id != role.id and candidate_id not in ordered:
                ordered.append(candidate_id)

        # Enrich with role-defined delegations and defaults
        for candidate in role.delegation_chain:
            if candidate and candidate != role.id and candidate not in ordered:
                ordered.append(candidate)
        for candidate in self.default_chain:
            if candidate and candidate != role.id and candidate not in ordered:
                ordered.append(candidate)
        return ordered

    async def route_query(self, query: Query, current_role: Role) -> Role:
        if await self.availability_service.is_available(current_role):
            return current_role

        records = await self.graph_client.fetch_delegates(current_role.id, query.content, limit=8)
        candidate_ids = await self.select_delegate(current_role, query.content, limit=8, precomputed=records)
        candidate_roles = await self.role_repository.get_roles(candidate_ids)

        # Map metadata from graph query for quick availability checks
        graph_records = {record["role_id"]: record for record in records}

        for candidate in candidate_roles:
            if not candidate.is_active:
                continue
            record = graph_records.get(candidate.id)
            availability_hint = (record or {}).get("availability")
            if availability_hint and availability_hint not in Neo4jAvailabilityService.AVAILABLE_STATES:
                continue
            if await self.availability_service.is_available(candidate):
                return candidate

        escalated = await self.escalation_service.escalate(current_role)
        if escalated.id != current_role.id and await self.availability_service.is_available(escalated):
            return escalated

        try:
            fallback = await self.skill_router.find_best_match(query.required_skills or current_role.required_skills)
        except DelegationFailureError as exc:
            logger.debug("Skill-based delegation failed: %s", exc)
            fallback = None

        if fallback and await self.availability_service.is_available(fallback):
            return fallback

        raise DelegationFailureError(
            error_code="DELEGATION_FAILED",
            message=f"No available delegate found for role '{current_role.id}'.",
            details={
                "role": current_role.id,
                "required_skills": list(query.required_skills),
                "candidate_ids": candidate_ids,
            },
        )


delegation_manager = DelegationManager()
