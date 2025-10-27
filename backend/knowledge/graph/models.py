"""Graph node and relationship models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class GraphNode:
    id: str
    labels: list[str]
    properties: Dict[str, object] = field(default_factory=dict)


@dataclass
class GraphRelationship:
    start_node: str
    end_node: str
    type: str
    properties: Dict[str, object] = field(default_factory=dict)
