from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.logging_setup import get_logger
from app.metrics import MARGIN_CHECK_FALLBACKS
from app.models import PortfolioSnapshot
from app.redis_bus import RedisBus

log = get_logger(module="clients")

MARGIN_CACHE_KEY = "sg:risk:cache:margin"
PORTFOLIO_CACHE_KEY = "sg:risk:cache:portfolio"


class BrokerServiceClient:
    """Resilient client for broker_service (8003).

    Margin checks must never block the risk pipeline indefinitely: on
    timeout / 5xx / connection failure we fall back to the last
    successfully cached margin snapshot in Redis. If no cache exists
    either, we degrade to a conservative synthetic snapshot derived
    from the portfolio NAV so the pipeline can still make a (more
    cautious) decision rather than stalling.
    """

    def __init__(self, base_url: str, redis_bus: RedisBus, mode: str, cache_ttl: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._redis = redis_bus
        self._mode = mode  # resilient | strict | disabled
        self._cache_ttl = cache_ttl
        self._http = httpx.AsyncClient(base_url=self._base_url, timeout=httpx.Timeout(2.5, connect=1.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.1, max=0.5),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
        reraise=True,
    )
    async def _fetch_margins(self) -> dict[str, Any]:
        resp = await self._http.get("/margins")
        resp.raise_for_status()
        return resp.json()

    async def get_margin_snapshot(self, fallback_nav_inr: float) -> dict[str, Any]:
        if self._mode == "disabled":
            return {"free_margin_inr": float("inf"), "total_margin_inr": float("inf"), "source": "disabled"}

        try:
            data = await self._fetch_margins()
            data["source"] = "live"
            await self._redis.set_hot_key(MARGIN_CACHE_KEY, data, ttl_seconds=self._cache_ttl * 10)
            return data
        except Exception as exc:
            log.warning("broker_margin_fetch_failed", error=str(exc), mode=self._mode)
            if self._mode == "strict":
                raise

            cached = await self._redis.get_hot_key(MARGIN_CACHE_KEY)
            if cached is not None:
                MARGIN_CHECK_FALLBACKS.labels(reason="cached").inc()
                cached["source"] = "cached_fallback"
                return cached

            MARGIN_CHECK_FALLBACKS.labels(reason="synthetic").inc()
            # Conservative synthetic snapshot: assume only 50% of NAV is free
            # margin so the check errs on the side of caution when broker
            # data is fully unavailable.
            return {
                "free_margin_inr": fallback_nav_inr * 0.5,
                "total_margin_inr": fallback_nav_inr,
                "source": "synthetic_fallback",
            }


class PortfolioClient:
    """Fetches portfolio/risk state, mirroring execution_orchestrator_service's
    pattern of reading Redis hot keys with HTTP fallback to broker_service."""

    def __init__(self, redis_bus: RedisBus, broker_base_url: str) -> None:
        self._redis = redis_bus
        self._http = httpx.AsyncClient(base_url=broker_base_url.rstrip("/"), timeout=httpx.Timeout(2.5, connect=1.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        cached = await self._redis.get_hot_key(PORTFOLIO_CACHE_KEY)
        if cached:
            return PortfolioSnapshot(**cached)
        try:
            resp = await self._http.get("/portfolio/snapshot")
            resp.raise_for_status()
            data = resp.json()
            await self._redis.set_hot_key(PORTFOLIO_CACHE_KEY, data, ttl_seconds=10)
            return PortfolioSnapshot(**data)
        except Exception as exc:
            log.error("portfolio_snapshot_unavailable", error=str(exc))
            # Last resort: empty/zero snapshot. Downstream checks treat
            # zero NAV as "halt everything" rather than "allow everything".
            return PortfolioSnapshot(
                nav_inr=0.0,
                cash_inr=0.0,
                peak_equity_inr=0.0,
                daily_pnl_inr=0.0,
                daily_start_equity_inr=0.0,
            )


class MarketDataClient:
    """Fetches volatility / correlation inputs from market_data_service (8002)."""

    def __init__(self, base_url: str, redis_bus: RedisBus) -> None:
        self._redis = redis_bus
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=httpx.Timeout(2.5, connect=1.0))

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get_volatility(self, symbol: str, window_days: int = 20) -> float | None:
        cache_key = f"sg:risk:cache:vol:{symbol}:{window_days}"
        cached = await self._redis.get_hot_key(cache_key)
        if cached is not None:
            return cached.get("annualized_vol_percent")
        try:
            resp = await self._http.get(f"/symbols/{symbol}/volatility", params={"window_days": window_days})
            resp.raise_for_status()
            data = resp.json()
            await self._redis.set_hot_key(cache_key, data, ttl_seconds=60)
            return data.get("annualized_vol_percent")
        except Exception as exc:
            log.warning("volatility_fetch_failed", symbol=symbol, error=str(exc))
            return None

    async def get_correlation_matrix(self, symbols: list[str], window_days: int = 60) -> dict[str, dict[str, float]] | None:
        if not symbols:
            return {}
        cache_key = f"sg:risk:cache:corr:{'-'.join(sorted(symbols))}:{window_days}"
        cached = await self._redis.get_hot_key(cache_key)
        if cached is not None:
            return cached
        try:
            resp = await self._http.post(
                "/correlation-matrix", json={"symbols": symbols, "window_days": window_days}
            )
            resp.raise_for_status()
            data = resp.json()
            await self._redis.set_hot_key(cache_key, data, ttl_seconds=120)
            return data
        except Exception as exc:
            log.warning("correlation_fetch_failed", symbols=symbols, error=str(exc))
            return None

    async def get_intraday_move_percent(self, symbol: str, window_minutes: int) -> float | None:
        try:
            resp = await self._http.get(
                f"/symbols/{symbol}/intraday-move", params={"window_minutes": window_minutes}
            )
            resp.raise_for_status()
            return resp.json().get("move_percent")
        except Exception as exc:
            log.warning("intraday_move_fetch_failed", symbol=symbol, error=str(exc))
            return None
