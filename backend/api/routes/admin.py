"""Administrative endpoints for TwinOps."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, PositiveInt

from backend.api.dependencies import get_current_user
from backend.core.auth import api_key_manager
from backend.core.config import settings
from backend.core.security import create_access_token
from backend.models import User

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_CLEARANCE = 8


class APIKeyCreateRequest(BaseModel):
    name: str
    email: EmailStr
    role: str = Field("service", min_length=2)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    clearance_level: PositiveInt = Field(5, le=10)
    expires_minutes: Optional[int] = Field(None, gt=0)


class APIKeyResponse(BaseModel):
    id: str
    key: str
    role: str
    name: str
    email: EmailStr
    clearance_level: int
    created_at: str


class APIKeySummary(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    clearance_level: int
    created_at: str
    expires_at: Optional[str] = None
    revoked: bool


class JWTIssueRequest(BaseModel):
    subject: str
    role: str = "user"
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    clearance_level: int = 0
    expires_minutes: int = Field(60, gt=0, le=24 * 60)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class JWTIssueResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    claims: Dict[str, Any]


@router.get("/health")
async def healthcheck() -> Dict[str, str]:
    """Liveness probe."""

    return {"status": "ok", "environment": settings.ENVIRONMENT}


@router.get("/config")
async def configuration_snapshot(current_user: User = Depends(get_current_user)) -> Dict[str, str]:
    """Return a limited configuration snapshot for admins."""

    _ensure_admin(current_user)
    return {
        "api_title": settings.API_TITLE,
        "environment": settings.ENVIRONMENT,
        "neo4j_uri": str(settings.NEO4J_URI),
        "pinecone_index": settings.PINECONE_INDEX,
    }


@router.post(
    "/api-keys",
    response_model=APIKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    payload: APIKeyCreateRequest,
    current_user: User = Depends(get_current_user),
) -> APIKeyResponse:
    _ensure_admin(current_user)
    expires = timedelta(minutes=payload.expires_minutes) if payload.expires_minutes else None
    token, record = await api_key_manager.create_key(
        name=payload.name,
        email=payload.email,
        role=payload.role,
        attributes=payload.attributes,
        clearance_level=payload.clearance_level,
        expires_in=expires,
    )
    return APIKeyResponse(
        id=record["id"],
        key=token,
        role=record["role"],
        name=record["name"],
        email=record["email"],
        clearance_level=record["clearance_level"],
        created_at=record["created_at"].isoformat(),
    )


@router.get(
    "/api-keys",
    response_model=List[APIKeySummary],
)
async def list_api_keys(
    include_revoked: bool = False,
    current_user: User = Depends(get_current_user),
) -> List[APIKeySummary]:
    _ensure_admin(current_user)
    records = await api_key_manager.list_keys(include_revoked=include_revoked)
    summaries: List[APIKeySummary] = []
    for record in records:
        summaries.append(
            APIKeySummary(
                id=record.get("id"),
                name=record.get("name"),
                email=record.get("email"),
                role=record.get("role", "service"),
                clearance_level=int(record.get("clearance_level", 5)),
                created_at=record.get("created_at").isoformat() if record.get("created_at") else "",
                expires_at=record.get("expires_at").isoformat() if record.get("expires_at") else None,
                revoked=bool(record.get("revoked", False)),
            )
        )
    return summaries


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    _ensure_admin(current_user)
    success = await api_key_manager.revoke_key(key_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")


@router.post(
    "/jwt",
    response_model=JWTIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_jwt(
    payload: JWTIssueRequest,
    current_user: User = Depends(get_current_user),
) -> JWTIssueResponse:
    _ensure_admin(current_user)
    expires = timedelta(minutes=payload.expires_minutes)
    claims: Dict[str, Any] = {
        "role": payload.role,
        "clearance": payload.clearance_level,
        "attributes": payload.attributes,
    }
    if payload.email:
        claims["email"] = payload.email
    if payload.name:
        claims["name"] = payload.name
    token = create_access_token(
        subject=payload.subject,
        expires_delta=expires,
        claims=claims,
    )
    expires_at = (datetime.utcnow() + expires).isoformat()
    return JWTIssueResponse(access_token=token, expires_at=expires_at, claims=claims)


def _ensure_admin(user: User) -> None:
    is_admin_role = user.role in {"system", "admin"}
    if is_admin_role or getattr(user, "clearance_level", 0) >= ADMIN_CLEARANCE:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
