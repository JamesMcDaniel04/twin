"""Security utilities and access control orchestration for TwinOps."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Optional, Protocol

from jose import JWTError, jwt

from backend.core.config import settings
from backend.core.exceptions import UnauthorizedError
from backend.utils.audit import audit_log


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
    claims: Optional[Dict[str, Any]] = None,
) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload: Dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def verify_access_token(token: str) -> Dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError as exc:
        raise UnauthorizedError("Invalid token") from exc


class RBACService(Protocol):
    async def has_access(self, role: str, resource: "Resource") -> bool:
        ...


class ABACService(Protocol):
    async def evaluate(self, attributes: Dict[str, Any], resource_attributes: Dict[str, Any]) -> bool:
        ...


class AuditLogger(Protocol):
    async def log_access_attempt(self, user: "User", resource: "Resource", granted: bool) -> None:
        ...

    async def log(self, payload: Dict[str, Any]) -> None:
        ...


class EncryptionService(Protocol):
    async def encrypt(self, value: Any) -> Any:
        ...


class User(Protocol):
    id: str
    role: str
    attributes: Dict[str, Any]
    clearance_level: int


class Resource(Protocol):
    id: str
    attributes: Dict[str, Any]
    classification: int


class SecurityManager:
    """Coordinates RBAC, ABAC, data classification, and audit logging."""

    def __init__(
        self,
        rbac_service: RBACService,
        abac_service: ABACService,
        audit_logger: AuditLogger,
        encryption_service: EncryptionService,
        pii_fields: Optional[Iterable[str]] = None,
    ) -> None:
        self._rbac = rbac_service
        self._abac = abac_service
        self.audit_logger = audit_logger
        self._encryption = encryption_service
        self.pii_fields = set(pii_fields or [])

    @audit_log
    async def check_access(self, user: User, resource: Resource) -> bool:
        if not await self.check_rbac(user.role, resource):
            await self.audit_logger.log_access_attempt(user, resource, granted=False)
            return False

        if not await self.check_abac(user.attributes, resource.attributes):
            await self.audit_logger.log_access_attempt(user, resource, granted=False)
            return False

        if resource.classification > getattr(user, "clearance_level", 0):
            await self.audit_logger.log_access_attempt(user, resource, granted=False)
            return False

        await self.audit_logger.log_access_attempt(user, resource, granted=True)
        return True

    async def check_rbac(self, role: str, resource: Resource) -> bool:
        return await self._rbac.has_access(role, resource)

    async def check_abac(self, attributes: Dict[str, Any], resource_attributes: Dict[str, Any]) -> bool:
        return await self._abac.evaluate(attributes, resource_attributes)

    async def encrypt_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        protected = dict(data)
        for field in self.pii_fields:
            if field in protected:
                protected[field] = await self.encrypt_field(protected[field])
        return protected

    async def encrypt_field(self, value: Any) -> Any:
        return await self._encryption.encrypt(value)
