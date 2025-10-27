"""Text chunking utilities."""

from __future__ import annotations

import re
from typing import Iterable, List


class TextChunker:
    """Semantic-aware text chunking."""

    sentence_pattern = re.compile(r"(?<=[.!?])\s+")

    def chunk(self, text: str, *, chunk_size: int, overlap: int) -> List[str]:
        sentences = [s.strip() for s in self.sentence_pattern.split(text.strip()) if s.strip()]
        if not sentences:
            return []

        chunks: List[str] = []
        current: List[str] = []
        current_length = 0

        for sentence in sentences:
            sentence_length = len(sentence)
            if current_length + sentence_length <= chunk_size or not current:
                current.append(sentence)
                current_length += sentence_length + 1
                continue

            chunks.append(" ".join(current))
            current_overlap = self._apply_overlap(current, overlap)
            current = current_overlap + [sentence]
            current_length = sum(len(s) for s in current) + len(current) - 1

        if current:
            chunks.append(" ".join(current))

        return chunks

    def _apply_overlap(self, sentences: Iterable[str], overlap: int) -> List[str]:
        collected: List[str] = []
        total = 0
        for sentence in reversed(list(sentences)):
            total += len(sentence)
            collected.append(sentence)
            if total >= overlap:
                break
        return list(reversed(collected))
