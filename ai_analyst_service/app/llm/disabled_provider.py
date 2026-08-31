"""
Disabled LLM provider — used when no API key is configured.

The ai_analyst_service starts and stays healthy; all other platform services
are completely unaffected. AI analysis endpoints return a 503 with a clear
message instead of crashing with a 500.
"""
from __future__ import annotations

from typing import AsyncIterator

from app.llm.base import LLMProvider, LLMProviderError
from app.models.domain import LLMRequest, LLMResponse, LLMUsage

_DISABLED_MSG = (
    "AI analysis is disabled: ANTHROPIC_API_KEY is not configured. "
    "Set it in sg-infra/.env and restart the ai_analyst_service to enable."
)


class DisabledProvider(LLMProvider):
    """Drop-in provider used when no LLM key is present.

    Every call raises LLMProviderError with a helpful message.
    The service boots normally; only AI-analysis endpoints are
    affected — all health/metrics/db endpoints continue to work.
    """

    name = "disabled"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise LLMProviderError(_DISABLED_MSG)

    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        raise LLMProviderError(_DISABLED_MSG)
        # Make the type-checker happy — this line is never reached
        yield  # type: ignore[misc]

    async def aclose(self) -> None:
        pass
