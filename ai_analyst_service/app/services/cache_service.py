from __future__ import annotations

import hashlib
import json

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import log
from app.core.metrics import CACHE_HITS, CACHE_MISSES
from app.models.domain import AnalysisCapability, AnalysisResult


def build_cache_key(capability: AnalysisCapability, params: dict, prompt_version: int) -> str:
    """Stable cache key over the capability, its request parameters, and the
    active prompt version — a prompt rollout naturally busts the cache for
    that capability instead of serving stale-template answers."""
    canonical = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"ai:cache:{capability.value}:v{prompt_version}:{digest}"


_TTL_BY_CAPABILITY = {
    AnalysisCapability.MARKET_SUMMARY: "cache_ttl_seconds_market_summary",
    AnalysisCapability.PORTFOLIO_REVIEW: "cache_ttl_seconds_portfolio_review",
}


def _ttl_for(capability: AnalysisCapability) -> int:
    attr = _TTL_BY_CAPABILITY.get(capability)
    if attr:
        return getattr(settings, attr)
    return settings.cache_ttl_seconds_default


class AnalysisCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str, capability: AnalysisCapability) -> AnalysisResult | None:
        if not settings.cache_enabled:
            return None
        try:
            raw = await self._redis.get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("cache_get_failed", error=str(exc))
            return None

        if raw is None:
            CACHE_MISSES.labels(capability=capability.value).inc()
            return None

        CACHE_HITS.labels(capability=capability.value).inc()
        result = AnalysisResult.model_validate_json(raw)
        result.cached = True
        return result

    async def set(self, key: str, capability: AnalysisCapability, result: AnalysisResult) -> None:
        if not settings.cache_enabled:
            return
        ttl = _ttl_for(capability)
        try:
            await self._redis.set(key, result.model_dump_json(), ex=ttl)
        except Exception as exc:  # noqa: BLE001
            # Caching is a cost optimisation, not correctness-critical —
            # never fail the request because Redis is unavailable.
            log.warning("cache_set_failed", error=str(exc))
