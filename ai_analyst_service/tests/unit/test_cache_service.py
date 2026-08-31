from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.domain import AnalysisCapability, AnalysisResult
from app.services.cache_service import AnalysisCache, build_cache_key


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


def _result(text: str = "Some explanation") -> AnalysisResult:
    return AnalysisResult(
        capability=AnalysisCapability.PORTFOLIO_REVIEW,
        generated_at=datetime.now(timezone.utc),
        model="claude-sonnet-4-6",
        text=text,
        prompt_version=1,
    )


def test_build_cache_key_is_stable_for_same_params():
    k1 = build_cache_key(AnalysisCapability.MARKET_SUMMARY, {"symbols": ["A", "B"]}, 1)
    k2 = build_cache_key(AnalysisCapability.MARKET_SUMMARY, {"symbols": ["A", "B"]}, 1)
    assert k1 == k2


def test_build_cache_key_changes_with_prompt_version():
    k1 = build_cache_key(AnalysisCapability.MARKET_SUMMARY, {"symbols": ["A"]}, 1)
    k2 = build_cache_key(AnalysisCapability.MARKET_SUMMARY, {"symbols": ["A"]}, 2)
    assert k1 != k2


def test_build_cache_key_changes_with_params():
    k1 = build_cache_key(AnalysisCapability.MARKET_SUMMARY, {"symbols": ["A"]}, 1)
    k2 = build_cache_key(AnalysisCapability.MARKET_SUMMARY, {"symbols": ["B"]}, 1)
    assert k1 != k2


@pytest.mark.asyncio
async def test_cache_miss_then_hit():
    redis = FakeRedis()
    cache = AnalysisCache(redis)
    key = build_cache_key(AnalysisCapability.PORTFOLIO_REVIEW, {}, 1)

    miss = await cache.get(key, AnalysisCapability.PORTFOLIO_REVIEW)
    assert miss is None

    result = _result()
    await cache.set(key, AnalysisCapability.PORTFOLIO_REVIEW, result)

    hit = await cache.get(key, AnalysisCapability.PORTFOLIO_REVIEW)
    assert hit is not None
    assert hit.text == result.text
    assert hit.cached is True


@pytest.mark.asyncio
async def test_cache_disabled_never_hits(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "cache_enabled", False)
    redis = FakeRedis()
    cache = AnalysisCache(redis)
    key = build_cache_key(AnalysisCapability.PORTFOLIO_REVIEW, {}, 1)

    await cache.set(key, AnalysisCapability.PORTFOLIO_REVIEW, _result())
    result = await cache.get(key, AnalysisCapability.PORTFOLIO_REVIEW)
    assert result is None
