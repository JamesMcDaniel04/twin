"""Audit logging utilities."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from functools import wraps
from inspect import iscoroutinefunction
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("twinops.audit")


class AuditLogger:
    """Structured audit logger."""

    def record(self, action: str, actor: str, details: Dict[str, Any]) -> None:
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "actor": actor,
            "details": details,
        }
        logger.info(json.dumps(payload))


audit_logger = AuditLogger()


def audit_log(func: Callable) -> Callable:
    """Decorator that emits structured audit records around function execution."""

    if iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            context_logger = _resolve_logger(kwargs)
            user_id = _resolve_user(kwargs)
            metadata = _build_metadata(func, kwargs)
            await _emit(context_logger, "start", user_id, metadata)
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                await _emit(context_logger, "error", user_id, metadata | {"error": str(exc)})
                raise
            await _emit(context_logger, "success", user_id, metadata)
            return result

        return async_wrapper

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        context_logger = _resolve_logger(kwargs)
        user_id = _resolve_user(kwargs)
        metadata = _build_metadata(func, kwargs)
        context_logger.record("start", user_id, metadata)
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - sync branch rarely used
            context_logger.record("error", user_id, metadata | {"error": str(exc)})
            raise
        context_logger.record("success", user_id, metadata)
        return result

    return sync_wrapper


def _resolve_logger(kwargs: Dict[str, Any]) -> AuditLogger:
    audit_ctx = kwargs.get("audit_ctx")
    if audit_ctx and getattr(audit_ctx, "audit_logger", None):
        return audit_ctx.audit_logger  # type: ignore[return-value]
    return audit_logger


def _resolve_user(kwargs: Dict[str, Any]) -> str:
    user = kwargs.get("current_user") or kwargs.get("user")
    if user and getattr(user, "id", None):
        return str(user.id)
    return "anonymous"


def _build_metadata(func: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    metadata = {
        "action": func.__qualname__,
    }
    if "payload" in kwargs and isinstance(kwargs["payload"], dict):
        metadata["payload_keys"] = list(kwargs["payload"].keys())
    return metadata


async def _emit(logger_obj: AuditLogger, event: str, user_id: str, metadata: Dict[str, Any]) -> None:
    log_method = getattr(logger_obj, "log", None)
    if callable(log_method):
        result = log_method({"event": event, "user": user_id, **metadata})
        if isinstance(result, Awaitable):
            await result
        return
    logger_obj.record(event, user_id, metadata)


__all__ = ["audit_logger", "audit_log", "AuditLogger"]
