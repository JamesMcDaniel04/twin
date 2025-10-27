from __future__ import annotations

import asyncio
import functools
import json
from datetime import datetime
from typing import Any, Awaitable, Callable, Coroutine, Dict, Optional, Protocol, TypeVar, Union, cast

AuditLoggerCallable = Callable[[Dict[str, Any]], Awaitable[None]]
F = TypeVar("F", bound=Callable[..., Any])


class SupportsAuditLogger(Protocol):
    async def log(self, payload: Dict[str, Any]) -> None:
        ...


def ensure_async(func: Callable[..., Any]) -> Callable[..., Coroutine[Any, Any, Any]]:
    if asyncio.iscoroutinefunction(func):
        return cast(Callable[..., Coroutine[Any, Any, Any]], func)

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))

    return wrapper


def audit_log(func: F) -> F:
    """Decorator that records execution metadata for audit and compliance."""

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        metadata = {
            "function": func.__qualname__,
            "module": func.__module__,
            "timestamp": datetime.utcnow().isoformat(),
            "args_preview": _safe_repr(args),
            "kwargs_preview": _safe_repr(kwargs),
        }
        audit_logger = _resolve_audit_logger(args, kwargs)
        if audit_logger:
            await audit_logger(metadata)

        func_async = ensure_async(func)
        try:
            result = await func_async(*args, **kwargs)
            metadata["status"] = "success"
            metadata["result_preview"] = _safe_repr(result)
            if audit_logger:
                await audit_logger(metadata)
            return result
        except Exception as exc:  # pragma: no cover - error branch captured by tests
            metadata["status"] = "error"
            metadata["error"] = repr(exc)
            if audit_logger:
                await audit_logger(metadata)
            raise

    return cast(F, async_wrapper)


def _resolve_audit_logger(args: Any, kwargs: Any) -> Optional[AuditLoggerCallable]:
    for value in list(args) + list(kwargs.values()):
        if isinstance(value, dict) and "audit_logger" in value:
            candidate = value["audit_logger"]
            if callable(candidate):
                return ensure_async(candidate)
        if hasattr(value, "audit_logger"):
            candidate = getattr(value, "audit_logger")
            if callable(candidate):
                return ensure_async(candidate)
        if isinstance(value, SupportsAuditLogger):
            return ensure_async(value.log)
    return None


def _safe_repr(value: Any, max_length: int = 512) -> str:
    try:
        text = json.dumps(value, default=str)
    except TypeError:
        text = repr(value)
    return text[:max_length]
