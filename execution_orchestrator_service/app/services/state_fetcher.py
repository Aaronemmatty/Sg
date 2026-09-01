"""State fetcher — portfolio and risk state with Redis hot path + HTTP fallback."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import STATE_FETCH_ERRORS, STATE_FETCH_LATENCY
from app.core.redis import get_redis
from app.models.domain import PortfolioState, PositionSnapshot, RiskState

settings = get_settings()
log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StateFetcher:
    """
    Fetch portfolio and risk state.

    Strategy:
      1. Try Redis (hot key written by portfolio_management / risk_engine).
      2. On cache miss or parse error, fall back to HTTP call.
      3. If HTTP also fails, return a safe default that will cause HOLD.
    """

    # ── Portfolio state ───────────────────────────────────────────────────────

    async def get_portfolio_state(
        self, portfolio_id: str
    ) -> Optional[PortfolioState]:
        t0 = time.perf_counter()
        state = await self._portfolio_from_redis(portfolio_id)
        if state:
            STATE_FETCH_LATENCY.labels(source="redis", state_type="portfolio").observe(
                time.perf_counter() - t0
            )
            return state

        # Redis miss → HTTP fallback
        t0 = time.perf_counter()
        state = await self._portfolio_from_http(portfolio_id)
        STATE_FETCH_LATENCY.labels(source="http", state_type="portfolio").observe(
            time.perf_counter() - t0
        )
        return state

    async def _portfolio_from_redis(
        self, portfolio_id: str
    ) -> Optional[PortfolioState]:
        try:
            redis = await get_redis()
            key = settings.REDIS_KEY_PORTFOLIO_STATE.format(portfolio_id=portfolio_id)
            raw = await redis.get(key)
            if raw:
                data = json.loads(raw)
                return PortfolioState(**data)
        except Exception as exc:
            log.warning(
                "portfolio_state_redis_miss",
                portfolio_id=portfolio_id,
                error=str(exc),
            )
            STATE_FETCH_ERRORS.labels(state_type="portfolio", source="redis").inc()
        return None

    async def _portfolio_from_http(
        self, portfolio_id: str
    ) -> Optional[PortfolioState]:
        try:
            url = f"{settings.BROKER_SERVICE_URL}/api/v1/portfolio/{portfolio_id}"
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                # Map broker_service response → PortfolioState
                positions = [
                    PositionSnapshot(
                        symbol=p["symbol"],
                        sector=p.get("sector"),
                        quantity=p.get("quantity", 0),
                        average_price=p.get("average_price", 0.0),
                        current_value_inr=p.get("current_value", 0.0),
                        weight_pct=p.get("weight_pct", 0.0),
                        correlation_group=p.get("correlation_group"),
                    )
                    for p in data.get("positions", [])
                ]
                return PortfolioState(
                    portfolio_id=portfolio_id,
                    total_value_inr=data.get("total_value", 0.0),
                    cash_inr=data.get("cash", 0.0),
                    equity_inr=data.get("equity", 0.0),
                    day_pnl_inr=data.get("day_pnl", 0.0),
                    total_pnl_inr=data.get("total_pnl", 0.0),
                    positions=positions,
                    as_of=_now(),
                )
        except Exception as exc:
            log.error(
                "portfolio_state_http_failed",
                portfolio_id=portfolio_id,
                error=str(exc),
            )
            STATE_FETCH_ERRORS.labels(state_type="portfolio", source="http").inc()
        return None

    # ── Risk state ────────────────────────────────────────────────────────────

    async def get_risk_state(self, portfolio_id: str) -> Optional[RiskState]:
        t0 = time.perf_counter()
        state = await self._risk_from_redis(portfolio_id)
        if state:
            STATE_FETCH_LATENCY.labels(source="redis", state_type="risk").observe(
                time.perf_counter() - t0
            )
            return state

        t0 = time.perf_counter()
        state = await self._risk_from_http(portfolio_id)
        STATE_FETCH_LATENCY.labels(source="http", state_type="risk").observe(
            time.perf_counter() - t0
        )
        return state

    async def _risk_from_redis(self, portfolio_id: str) -> Optional[RiskState]:
        try:
            redis = await get_redis()
            key = settings.REDIS_KEY_RISK_STATE.format(portfolio_id=portfolio_id)
            raw = await redis.get(key)
            if raw:
                data = json.loads(raw)
                return RiskState(**data)
        except Exception as exc:
            log.warning(
                "risk_state_redis_miss",
                portfolio_id=portfolio_id,
                error=str(exc),
            )
            STATE_FETCH_ERRORS.labels(state_type="risk", source="redis").inc()
        return None

    async def _risk_from_http(self, portfolio_id: str) -> Optional[RiskState]:
        """
        Fall back to risk_engine once it exists (port 8007).
        For now, return a permissive default so the orchestrator
        can still operate before risk_engine is deployed.
        """
        try:
            url = f"{settings.RISK_ENGINE_URL}/api/v1/risk/state/{portfolio_id}"
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                return RiskState(
                    portfolio_id=portfolio_id,
                    daily_loss_inr=data.get("daily_loss_inr", 0.0),
                    daily_loss_limit_inr=data.get(
                        "daily_loss_limit_inr",
                        # Fallback: 2% of ACCOUNT_CAPITAL_INR when risk_engine
                        # doesn't return its own limit value.
                        settings.ACCOUNT_CAPITAL_INR * settings.DAILY_LOSS_LIMIT_PCT,
                    ),
                    drawdown_pct=data.get("drawdown_pct", 0.0),
                    max_drawdown_pct=data.get(
                        "max_drawdown_pct", settings.MAX_PORTFOLIO_DRAWDOWN_PCT
                    ),
                    kill_switch_active=data.get("kill_switch_active", False),
                    open_intents_count=data.get("open_intents_count", 0),
                    correlation_matrix=data.get("correlation_matrix", {}),
                    as_of=_now(),
                )
        except Exception as exc:
            log.warning(
                "risk_state_http_failed",
                portfolio_id=portfolio_id,
                error=str(exc),
            )
            STATE_FETCH_ERRORS.labels(state_type="risk", source="http").inc()

        # Safe permissive default — lets pipeline proceed with internal checks
        log.warning(
            "risk_state_using_defaults",
            portfolio_id=portfolio_id,
        )
        return RiskState(
            portfolio_id=portfolio_id,
            daily_loss_inr=0.0,
            # 2% of configured capital reference as the last-resort fallback.
            daily_loss_limit_inr=settings.ACCOUNT_CAPITAL_INR * settings.DAILY_LOSS_LIMIT_PCT,
            drawdown_pct=0.0,
            max_drawdown_pct=settings.MAX_PORTFOLIO_DRAWDOWN_PCT,
            kill_switch_active=False,
            open_intents_count=0,
            correlation_matrix={},
            as_of=_now(),
        )
