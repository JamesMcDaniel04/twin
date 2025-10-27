"""Digital twin management endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List

from fastapi import APIRouter, HTTPException, status

try:  # Optional dependency for runtime environments without MongoDB client
    from motor.motor_asyncio import AsyncIOMotorCollection  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    AsyncIOMotorCollection = Any  # type: ignore
from pydantic import BaseModel, Field

from backend.core.database import database_manager
from backend.models.person import Person
from backend.models.role import Role

router = APIRouter(prefix="/twins", tags=["twins"])


class TwinCreateRequest(BaseModel):
    person: Person
    roles: List[Role] = Field(default_factory=list)


class TwinResponse(BaseModel):
    id: str
    person: Person
    roles: List[Role]
    created_at: datetime
    updated_at: datetime


def _twin_collection() -> AsyncIOMotorCollection:
    mongodb = database_manager.mongodb
    if mongodb is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Twin persistence store is unavailable. Ensure MongoDB is configured.",
        )
    return mongodb["twinops"]["twins"]


def _decode_twin(document: dict) -> TwinResponse:
    person = Person.model_validate(document["person"])
    roles = [Role.model_validate(role) for role in document.get("roles", [])]
    created_at = document.get("created_at") or datetime.utcnow()
    updated_at = document.get("updated_at") or created_at
    return TwinResponse(id=str(document.get("_id")), person=person, roles=roles, created_at=created_at, updated_at=updated_at)


@router.post("/", response_model=TwinResponse, status_code=status.HTTP_201_CREATED)
async def create_twin(payload: TwinCreateRequest) -> TwinResponse:
    """Create a new digital twin entity."""

    collection = _twin_collection()
    twin_id = str(uuid.uuid4())
    timestamp = datetime.utcnow()

    document = {
        "_id": twin_id,
        "person": payload.person.model_dump(mode="python"),
        "roles": [role.model_dump(mode="python") for role in payload.roles],
        "created_at": timestamp,
        "updated_at": timestamp,
    }

    await collection.insert_one(document)
    return _decode_twin(document)


@router.get("/{twin_id}", response_model=TwinResponse)
async def get_twin(twin_id: str) -> TwinResponse:
    """Retrieve a previously created digital twin."""

    collection = _twin_collection()
    document = await collection.find_one({"_id": twin_id})
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Twin not found")
    return _decode_twin(document)


@router.get("/", response_model=List[TwinResponse])
async def list_twins() -> List[TwinResponse]:
    """List all digital twins persisted in the knowledge store."""

    collection = _twin_collection()
    cursor = collection.find().sort("person.name", 1)
    documents = await cursor.to_list(length=200)
    return [_decode_twin(doc) for doc in documents]
