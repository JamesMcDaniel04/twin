"""Delegation logic for TwinOps workflows.

This module coordinates availability, delegation chains, graph suggestions,
and skill-based fallbacks to determine the best role to handle a request.
It is intentionally backend-agnostic so that tests and the public API can
inject lightweight in-memory collaborators, while production deployments
can wire Neo4j-backed services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Protocol, Sequence

from backend.core.exceptions import DelegationFailureError
from backend.models.query import Query
from backend.models.role import Person, Role

logger = logging.getLogger(__name__)


class AvailabilityService(Protocol):
    async def is_available(self, role: Role) -> bool: ...

    async def resolve_person(self, role: Role) -> Optional[Person]: ...


class DelegationGraphClient(Protocol):
    async def run(self, query: str, parameters: Dict[str, object]) -> Sequence[Dict[str, object]]: ...


class RoleRepository(Protocol):
    async def get_role(self, role_id: str) -> Role: ...

    async def get_roles(self, role_ids: Sequence[str]) -> List[Role]: ...


class EscalationService(Protocol):
    async def escalate(self, current_role: Role) -> Role: ...


class SkillRouter(Protocol):
    async def find_best_match(self, required_skills: Sequence[str]) -> Role: ...


@dataclass
class _NullAvailabilityService:
    """Fallback availability service that always reports roles as available."""

    async def is_available(self, role: Role) -> bool:  # pragma: no cover - trivial
        return bool(role.is_active)

    async def resolve_person(self, role: Role) -> Optional[Person]:  # pragma: no cover - trivial
        return None


@dataclass
class _NullRoleRepository:
    """Fallback repository that only knows about roles passed at runtime."""

    async def get_role(self, role_id: str) -> Role:
        raise DelegationFailureError(
            error_code="ROLE_NOT_AVAILABLE",
            message=f"Role '{role_id}' is not registered in the delegation repository.",
        )

    async def get_roles(self, role_ids: Sequence[str]) -> List[Role]:
        if not role_ids:
            return []
        raise DelegationFailureError(
            error_code="ROLE_NOT_AVAILABLE",
            message="Delegation repository cannot resolve requested roles.",
            details={"role_ids": list(role_ids)},
        )


@dataclass
class _NullEscalationService:
    async def escalate(self, current_role: Role) -> Role:  # pragma: no cover - trivial
        return current_role


@dataclass
class _NullSkillRouter:
    async def find_best_match(self, required_skills: Sequence[str]) -> Role:
        raise DelegationFailureError(
            error_code="DELEGATION_FAILED",
            message="No fallback skill router configured.",
            details={"required_skills": list(required_skills)},
        )


class DelegationManager:
    """Select appropriate delegate roles for a given responsibility."""

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
        self.availability_service = availability_service or _NullAvailabilityService()
        self.graph_client = graph_client
        self.role_repository = role_repository or _NullRoleRepository()
        self.escalation_service = escalation_service or _NullEscalationService()
        self.skill_router = skill_router or _NullSkillRouter()
        self.fallback_chain = [item for item in (fallback_chain or ("incident_commander", "ops_lead", "sre_oncall")) if item]

    async def select_delegate(
        self,
        role: Role,
        responsibility_hint: Optional[str] = None,
        *,
        limit: int = 10,
    ) -> List[str]:
        """Return ordered delegate role IDs derived from graph + role metadata."""

        ordered: List[str] = []
        seen = {role.id}

        # 1. Graph suggestions (if available)
        if self.graph_client is not None:
            try:
                records = await self.graph_client.run(
                    "delegation_chain",
                    {"role_id": role.id, "responsibility": responsibility_hint},
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Delegation graph lookup failed: %s", exc)
            else:
                for record in records:
                    candidate = (
                        record.get("role_id")
                        or record.get("id")
                        or record.get("delegate_id")
                    )
                    if candidate and candidate not in seen:
                        ordered.append(candidate)
                        seen.add(candidate)
                        if len(ordered) >= limit:
                            return ordered

        # 2. Role-defined delegation chain
        for candidate in role.delegation_chain:
            if candidate and candidate not in seen:
                ordered.append(candidate)
                seen.add(candidate)
                if len(ordered) >= limit:
                    return ordered

        # 3. Static fallback chain
        for candidate in self.fallback_chain:
            if candidate and candidate not in seen:
                ordered.append(candidate)
                seen.add(candidate)
                if len(ordered) >= limit:
                    return ordered

        return ordered

    async def route_query(self, query: Query, current_role: Role) -> Role:
        """Return the role that should own the provided query."""

        if await self.availability_service.is_available(current_role):
            return current_role

        candidate_ids = await self.select_delegate(current_role, query.content, limit=16)
        candidate_roles = await self._safe_get_roles(candidate_ids)

        for candidate in candidate_roles:
            if not candidate.is_active:
                continue
            try:
                if await self.availability_service.is_available(candidate):
                    return candidate
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Availability check failed for role %s: %s", candidate.id, exc)

        escalated = await self.escalation_service.escalate(current_role)
        if escalated.id != current_role.id and await self._is_role_available(escalated):
            return escalated

        fallback_skills = query.required_skills or current_role.required_skills
        if fallback_skills:
            try:
                fallback_role = await self.skill_router.find_best_match(fallback_skills)
            except DelegationFailureError as exc:
                logger.debug("Skill router could not resolve delegate: %s", exc)
            else:
                if fallback_role.id not in {current_role.id, *(role.id for role in candidate_roles)}:
                    if await self._is_role_available(fallback_role):
                        return fallback_role

        raise DelegationFailureError(
            error_code="DELEGATION_FAILED",
            message=f"No available delegate found for role '{current_role.id}'.",
            details={
                "role": current_role.id,
                "required_skills": list(query.required_skills),
                "candidates": candidate_ids,
            },
        )

    async def _safe_get_roles(self, role_ids: Sequence[str]) -> List[Role]:
        if not role_ids:
            return []
        try:
            return await self.role_repository.get_roles(role_ids)
        except DelegationFailureError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Failed to resolve candidate roles %s: %s", role_ids, exc)
            raise DelegationFailureError(
                error_code="ROLE_RESOLUTION_FAILED",
                message="Unable to resolve candidate roles.",
                details={"role_ids": list(role_ids)},
            ) from exc

    async def _is_role_available(self, role: Role) -> bool:
        try:
            return await self.availability_service.is_available(role)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Availability check errored for %s: %s", role.id, exc)
            return False


delegation_manager = DelegationManager()
