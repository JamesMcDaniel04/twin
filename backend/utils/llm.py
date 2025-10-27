"""Utilities for interacting with LLM providers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from openai import AsyncOpenAI

from backend.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Coordinate interactions with primary and fallback LLM providers."""

    def __init__(self) -> None:
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        try:
            from anthropic import AsyncAnthropic  # type: ignore

            self.claude = AsyncAnthropic(api_key=settings.CLAUDE_API_KEY)
        except ImportError:  # pragma: no cover - optional dependency
            self.claude = None

    async def chat(self, messages: List[Dict[str, str]], *, model: str | None = None) -> str:
        """Send a chat completion request with fallback to Claude."""

        model = model or settings.OPENAI_MODEL
        try:
            response = await self.openai.chat.completions.create(model=model, messages=messages)
            return response.choices[0].message.content
        except Exception as exc:
            logger.error("OpenAI chat failed: %s", exc)

        if self.claude:
            try:
                claude_response = await self.claude.messages.create(
                    model=settings.CLAUDE_MODEL,
                    max_tokens=800,
                    messages=messages,
                )
                return claude_response.content[0].text
            except Exception as exc:  # pragma: no cover - optional fallback
                logger.error("Claude chat failed: %s", exc)

        raise RuntimeError("All LLM providers failed")


llm_client = LLMClient()
