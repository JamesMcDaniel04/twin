"""Document parsing utilities."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedDocument:
    text: str
    metadata: dict


class DocumentParser:
    """Parse raw document bytes into structured text."""

    async def parse(self, content: bytes, mime_type: str) -> ParsedDocument:
        if mime_type in {"text/plain", "application/json"}:
            text = content.decode("utf-8", errors="ignore")
        else:
            # Placeholder: convert binary formats via fallback
            text = self._fallback_binary_decode(content)
        return ParsedDocument(text=text, metadata={"mime_type": mime_type})

    def _fallback_binary_decode(self, content: bytes) -> str:
        buffer = io.BytesIO(content)
        snippet = buffer.read().decode("utf-8", errors="ignore")
        return snippet
