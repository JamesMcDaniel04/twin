"""Input validation helpers."""

from __future__ import annotations

import re


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def require_uuid(value: str) -> str:
    if not UUID_PATTERN.match(value):
        raise ValueError("Expected UUID formatted string")
    return value


def require_non_empty(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("Value must not be empty")
    return value.strip()
