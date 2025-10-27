"""Audit logging utilities."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict

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
