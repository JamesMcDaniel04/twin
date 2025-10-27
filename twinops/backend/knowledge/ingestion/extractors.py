"""Metadata and entity extraction utilities."""

from __future__ import annotations

import re
from typing import Dict, List


class EntityExtractor:
    """Primitive entity extractor leveraging heuristics."""

    person_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b")

    async def extract(self, text: str) -> List[Dict[str, str]]:
        people = {match.group(1) for match in self.person_pattern.finditer(text)}
        return [{"type": "Person", "name": name} for name in people]


class MetadataExtractor:
    """Derive metadata from parsed documents."""

    async def extract(self, parsed_document) -> Dict[str, str]:
        length = len(parsed_document.text.split())
        return {"word_count": str(length), **parsed_document.metadata}
