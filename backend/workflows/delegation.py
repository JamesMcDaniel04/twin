"""Delegation logic for TwinOps workflows."""

from __future__ import annotations

from typing import List

from backend.models.role import Role


class DelegationManager:
    """Select appropriate delegate roles for a given responsibility."""

    def __init__(self) -> None:
        self.default_delegate_chain = ["incident_commander", "ops_lead", "sre_oncall"]

    def select_delegate(self, role: Role, responsibility: str) -> List[str]:
        """Return delegate role IDs ordered by suitability."""

        # Simple heuristic: first include explicit delegations defined on the role,
        # then fallback to the default delegate chain.
        delegates = list(dict.fromkeys(role.delegations))
        for candidate in self.default_delegate_chain:
            if candidate not in delegates:
                delegates.append(candidate)
        return delegates


delegation_manager = DelegationManager()
