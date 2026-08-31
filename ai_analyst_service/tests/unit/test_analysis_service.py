from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.llm.base import LLMProviderError
from app.models.domain import (
    AnalysisCapability,
    AnalysisResult,
    LLMResponse,
    LLMUsage,
    PromptTemplate,
)
from app.services.analysis_service import AnalysisService
from app.services.rate_limiter import RateLimitExceeded


def _template() -> PromptTemplate:
    return PromptTemplate(
        id=uuid.uuid4(),
        capability=AnalysisCapability.PORTFOLIO_REVIEW,
        version=1,
        system_prompt="You are a portfolio analyst.",
        user_template="<data>{context_json}</data><user_note>{user_note}</user_note>",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


def _make_service(prompt_manager=None, cache=None, rate_limiter=None, llm=None, repo=None):
    repo = repo or AsyncMock()
    prompt_manager = prompt_manager or AsyncMock(get_active_template=AsyncMock(return_value=_template()))
    cache = cache or AsyncMock(get=AsyncMock(return_value=None), set=AsyncMock())
    rate_limiter = rate_limiter or AsyncMock(check_and_increment=AsyncMock())
    llm = llm or AsyncMock()
    return AnalysisService(repo, prompt_manager, cache, rate_limiter, llm)


@pytest.mark.asyncio
async def test_prepare_returns_cached_result_without_calling_rate_limiter():
    cached_result = AnalysisResult(
        capability=AnalysisCapability.PORTFOLIO_REVIEW,
        generated_at=datetime.now(timezone.utc),
        model="claude-sonnet-4-6",
        text="cached text",
        prompt_version=1,
    )
    cache = AsyncMock(get=AsyncMock(return_value=cached_result), set=AsyncMock())
    rate_limiter = AsyncMock(check_and_increment=AsyncMock())
    service = _make_service(cache=cache, rate_limiter=rate_limiter)

    prepared = await service.prepare(
        AnalysisCapability.PORTFOLIO_REVIEW, {"snapshot": {}}, [], None, {}, "user-1"
    )

    assert prepared.cached_result is cached_result
    rate_limiter.check_and_increment.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_enforces_rate_limit_on_cache_miss():
    rate_limiter = AsyncMock(check_and_increment=AsyncMock(side_effect=RateLimitExceeded("user", 10)))
    service = _make_service(rate_limiter=rate_limiter)

    with pytest.raises(RateLimitExceeded):
        await service.prepare(AnalysisCapability.PORTFOLIO_REVIEW, {}, [], None, {}, "user-1")


@pytest.mark.asyncio
async def test_run_calls_llm_and_caches_result_on_cache_miss():
    llm = AsyncMock()
    llm.generate.return_value = LLMResponse(
        text="Your portfolio is up 5% this month.",
        model="claude-sonnet-4-6",
        usage=LLMUsage(input_tokens=100, output_tokens=50),
    )
    cache = AsyncMock(get=AsyncMock(return_value=None), set=AsyncMock())
    service = _make_service(llm=llm, cache=cache)

    prepared = await service.prepare(
        AnalysisCapability.PORTFOLIO_REVIEW, {"snapshot": {}}, [], "be brief", {}, "user-1"
    )
    result = await service.run(prepared)

    assert result.text == "Your portfolio is up 5% this month."
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    cache.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_propagates_llm_provider_error():
    llm = AsyncMock()
    llm.generate.side_effect = LLMProviderError("upstream is down")
    service = _make_service(llm=llm)

    prepared = await service.prepare(AnalysisCapability.PORTFOLIO_REVIEW, {}, [], None, {}, "user-1")
    with pytest.raises(LLMProviderError):
        await service.run(prepared)


@pytest.mark.asyncio
async def test_stream_yields_deltas_and_caches_full_text():
    async def fake_stream(_request):
        for chunk in ["Hello", " ", "world"]:
            yield chunk

    llm = AsyncMock()
    llm.generate_stream = fake_stream
    cache = AsyncMock(get=AsyncMock(return_value=None), set=AsyncMock())
    service = _make_service(llm=llm, cache=cache)

    prepared = await service.prepare(AnalysisCapability.PORTFOLIO_REVIEW, {}, [], None, {}, "user-1")
    collected = [chunk async for chunk in service.stream(prepared)]

    assert "".join(collected) == "Hello world"
    cache.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_yields_cached_text_directly_without_llm_call():
    cached_result = AnalysisResult(
        capability=AnalysisCapability.PORTFOLIO_REVIEW,
        generated_at=datetime.now(timezone.utc),
        model="claude-sonnet-4-6",
        text="cached answer",
        prompt_version=1,
    )
    cache = AsyncMock(get=AsyncMock(return_value=cached_result), set=AsyncMock())
    llm = AsyncMock()
    service = _make_service(cache=cache, llm=llm)

    prepared = await service.prepare(AnalysisCapability.PORTFOLIO_REVIEW, {}, [], None, {}, "user-1")
    collected = [chunk async for chunk in service.stream(prepared)]

    assert collected == ["cached answer"]
    llm.generate_stream.assert_not_called()
