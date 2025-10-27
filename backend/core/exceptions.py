"""Custom exception hierarchy for TwinOps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import status


class ApplicationError(Exception):
    """Base application error with HTTP semantics."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "application_error"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        self.message = message


class NotFoundError(ApplicationError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ValidationError(ApplicationError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"


class UnauthorizedError(ApplicationError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


@dataclass
class TwinOpsError(Exception):
    """Base class for application specific errors with structured payloads."""

    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        base = f"[{self.error_code}] {self.message}"
        if self.details:
            return f"{base} :: {self.details}"
        return base


class KnowledgeNotFoundError(TwinOpsError):
    """Raised when no relevant knowledge exists for a query."""


class DelegationFailureError(TwinOpsError):
    """Raised when delegation routing cannot find a suitable assignee."""


class GraphTraversalError(TwinOpsError):
    """Raised when the graph traversal layer fails to serve a request."""
