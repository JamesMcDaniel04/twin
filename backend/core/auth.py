"""Authentication helper utilities (API keys, JWT bootstrap)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from backend.core.database import database_manager


class APIKeyManager:
    """Persist and verify API keys backed by MongoDB."""

    def __init__(self, collection: str = "api_keys") -> None:
        self.collection_name = collection

    async def _collection(self):
        mongodb = database_manager.mongodb
        if mongodb is None:
            return None
        return mongodb["twinops"][self.collection_name]

    async def create_key(
        self,
        *,
        name: str,
        email: str,
        role: str,
        attributes: Optional[Dict[str, Any]] = None,
        clearance_level: int = 5,
        expires_in: Optional[timedelta] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        token = secrets.token_urlsafe(32)
        hashed = self._hash(token)
        record = {
            "id": secrets.token_hex(8),
            "name": name,
            "email": email,
            "role": role,
            "attributes": attributes or {},
            "hashed_key": hashed,
            "created_at": datetime.utcnow(),
            "revoked": False,
            "clearance_level": clearance_level,
        }
        if expires_in:
            record["expires_at"] = datetime.utcnow() + expires_in

        collection = await self._collection()
        if collection is None:
            raise RuntimeError("MongoDB unavailable; cannot persist API key.")
        await collection.insert_one(record)
        return token, record

    async def list_keys(self, include_revoked: bool = False) -> List[Dict[str, Any]]:
        collection = await self._collection()
        if collection is None:
            return []
        query: Dict[str, Any] = {}
        if not include_revoked:
            query["revoked"] = False
        cursor = collection.find(query).sort("created_at", -1)
        results: List[Dict[str, Any]] = []
        async for document in cursor:
            document.pop("hashed_key", None)
            results.append(document)
        return results

    async def revoke_key(self, key_id: str) -> bool:
        collection = await self._collection()
        if collection is None:
            return False
        result = await collection.update_one({"id": key_id}, {"$set": {"revoked": True}})
        return result.modified_count > 0

    async def resolve(self, raw_key: str) -> Optional[Dict[str, Any]]:
        collection = await self._collection()
        if collection is None:
            return None
        hashed = self._hash(raw_key)
        document = await collection.find_one({"hashed_key": hashed, "revoked": False})
        if not document:
            return None
        if document.get("expires_at") and document["expires_at"] < datetime.utcnow():
            await collection.update_one({"_id": document["_id"]}, {"$set": {"revoked": True}})
            return None
        document.pop("hashed_key", None)
        return document

    def _hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


api_key_manager = APIKeyManager()

__all__ = ["api_key_manager", "APIKeyManager"]
