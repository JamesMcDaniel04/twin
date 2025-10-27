"""Digital twin management endpoints."""

from __future__ import annotations

import uuid
from typing import Dict, List

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.models.person import Person
from backend.models.role import Role

router = APIRouter(prefix="/twins", tags=["twins"])

_IN_MEMORY_TWINS: Dict[str, Dict[str, object]] = {}


class TwinCreateRequest(BaseModel):
    person: Person
    roles: List[Role] = Field(default_factory=list)


class TwinResponse(BaseModel):
    id: str
    person: Person
    roles: List[Role]


@router.post("/", response_model=TwinResponse, status_code=status.HTTP_201_CREATED)
async def create_twin(payload: TwinCreateRequest) -> TwinResponse:
    """Create a new digital twin entity."""

    twin_id = str(uuid.uuid4())
    _IN_MEMORY_TWINS[twin_id] = {"person": payload.person, "roles": payload.roles}

    return TwinResponse(id=twin_id, person=payload.person, roles=payload.roles)


@router.get("/{twin_id}", response_model=TwinResponse)
async def get_twin(twin_id: str) -> TwinResponse:
    """Retrieve a previously created digital twin."""

    twin = _IN_MEMORY_TWINS.get(twin_id)
    if not twin:
        raise HTTPException(status_code=404, detail="Twin not found")

    return TwinResponse(id=twin_id, person=twin["person"], roles=twin["roles"])


@router.get("/", response_model=List[TwinResponse])
async def list_twins() -> List[TwinResponse]:
    """List all digital twins (temporary in-memory implementation)."""

    return [
        TwinResponse(id=twin_id, person=value["person"], roles=value["roles"]) for twin_id, value in _IN_MEMORY_TWINS.items()
    ]
