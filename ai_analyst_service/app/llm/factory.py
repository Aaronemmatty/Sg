from __future__ import annotations

from app.core.config import settings
from app.core.logging import log
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.base import LLMProvider
from app.llm.disabled_provider import DisabledProvider

_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        if not settings.anthropic_api_key:
            log.warning(
                "llm_provider_disabled",
                reason="ANTHROPIC_API_KEY not set",
                effect="AI analysis endpoints will return 503 until key is configured",
            )
            _provider = DisabledProvider()
        elif settings.llm_provider == "anthropic":
            _provider = AnthropicProvider()
        else:
            raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
    return _provider


async def close_llm_provider() -> None:
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None
