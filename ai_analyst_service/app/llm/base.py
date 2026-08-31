from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from app.models.domain import LLMRequest, LLMResponse


class LLMProviderError(Exception):
    """Raised for any provider failure after retries are exhausted."""


class LLMProvider(ABC):
    """Provider-agnostic interface the rest of the service talks to.

    Concrete implementations (Anthropic today, others later) only need to
    satisfy this contract — nothing else in the codebase should import a
    provider-specific SDK or HTTP client directly.
    """

    name: str

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Single non-streaming completion."""

    @abstractmethod
    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Yields text deltas as they arrive. The final usage/stop_reason are
        not available mid-stream with most providers; callers needing them
        should also be prepared to call generate() or capture them from a
        sentinel emitted by the implementation if documented."""

    @abstractmethod
    async def aclose(self) -> None: ...
