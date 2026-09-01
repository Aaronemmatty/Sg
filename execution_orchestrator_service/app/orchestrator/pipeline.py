"""
Execution Orchestrator pipeline.

Receives an AggregatedSignal, fetches state, runs all eligibility
checks, computes allocation, and produces a TradeIntent.

This is the central decision engine — it does NOT place orders.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import (
    ALLOCATION_INR,
    ELIGIBILITY_CHECKS,
    ORCHESTRATION_LATENCY,
    REJECTION_REASONS,
    SIGNALS_RECEIVED,
)
from app.core.tracing import get_tracer
from app.models.domain import (
    AggregatedSignal,
    AllocationResult,
    EligibilityResult,
    IntentStatus,
    MarketRegime,
    PortfolioState,
    RejectionReason,
    RiskState,
    TradeAction,
    TradeIntent,
)
from app.orchestrator.allocator import compute_allocation
from app.orchestrator.eligibility import run_all_checks
from app.services.state_fetcher import StateFetcher

settings = get_settings()
log = get_logger(__name__)


def _resolve_regime(signal: AggregatedSignal, regime_cache: dict[str, str]) -> str:
    """Prefer regime from signal, fall back to locally cached regime."""
    if signal.regime:
        return signal.regime
    cached = regime_cache.get(signal.symbol)
    if cached:
        return cached
    return MarketRegime.UNKNOWN.value


def _determine_status(
    checks: list[EligibilityResult],
    signal: AggregatedSignal,
    allocation: AllocationResult,
) -> tuple[IntentStatus, list[RejectionReason], Optional[str]]:
    """
    Aggregate check results into final status.

    Rules:
      - Any HARD failure (daily_loss, drawdown, kill_switch) → REJECTED
      - Confidence < threshold → REJECTED
      - Allocation too small → REJECTED
      - HOLD signal → HOLD regardless of checks
      - All checks pass → ELIGIBLE
    """
    if signal.final_signal == TradeAction.HOLD:
        return IntentStatus.HOLD, [], "Signal action is HOLD"

    failures = [r for r in checks if not r.passed]

    if not failures:
        # Allocation floor check (post-eligibility)
        if allocation.allocation_inr < settings.MIN_ALLOCATION_INR:
            return (
                IntentStatus.REJECTED,
                [RejectionReason.ALLOCATION_TOO_SMALL],
                f"allocation={allocation.allocation_inr:.0f} < min={settings.MIN_ALLOCATION_INR:.0f}",
            )
        return IntentStatus.ELIGIBLE, [], None

    reasons = [f.reason for f in failures if f.reason]
    details = "; ".join(f.detail for f in failures if f.detail)
    return IntentStatus.REJECTED, reasons, details or None


class OrchestratorPipeline:
    """
    Main pipeline — stateless, instantiated once per signal.
    State is injected via StateFetcher.
    """

    def __init__(
        self,
        state_fetcher: StateFetcher,
        regime_cache: dict[str, str],
    ) -> None:
        self._fetcher = state_fetcher
        self._regime_cache = regime_cache

    async def process(
        self,
        signal: AggregatedSignal,
        portfolio_id: Optional[str] = None,
    ) -> tuple[TradeIntent, list[EligibilityResult], PortfolioState, RiskState]:
        """
        Full orchestration pipeline.

        Returns (TradeIntent, all_checks, portfolio_state, risk_state)
        so the caller can persist audit records with full context.
        """
        tracer = get_tracer()
        t0 = time.perf_counter()

        with tracer.start_as_current_span("orchestrator.process") as span:
            span.set_attribute("symbol", signal.symbol)
            span.set_attribute("confidence", signal.confidence)
            span.set_attribute("action", signal.final_signal.value)

            SIGNALS_RECEIVED.labels(symbol=signal.symbol).inc()

            pid = portfolio_id or settings.DEFAULT_PORTFOLIO_ID
            correlation_id = str(uuid4())
            market_regime = _resolve_regime(signal, self._regime_cache)

            # ── 1. Fetch state ────────────────────────────────────────────────
            with tracer.start_as_current_span("orchestrator.fetch_state"):
                portfolio, risk = await self._fetch_state(pid)

            span.set_attribute("portfolio_value_inr", portfolio.total_value_inr)
            span.set_attribute("daily_loss_inr", risk.daily_loss_inr)
            span.set_attribute("market_regime", market_regime)

            # ── 2. Eligibility checks ─────────────────────────────────────────
            with tracer.start_as_current_span("orchestrator.eligibility"):
                checks = await run_all_checks(signal, portfolio, risk)

            # ── 3. Allocation ─────────────────────────────────────────────────
            with tracer.start_as_current_span("orchestrator.allocation"):
                allocation = compute_allocation(
                    confidence=signal.confidence,
                    portfolio=portfolio,
                    market_regime=market_regime,
                )

            # ── 4. Determine status ───────────────────────────────────────────
            status, rejection_reasons, rejection_detail = _determine_status(
                checks, signal, allocation
            )

            # ── 5. Build intent ───────────────────────────────────────────────
            intent = TradeIntent(
                symbol=signal.symbol,
                action=signal.final_signal,
                product=settings.PRODUCT_TYPE,
                confidence=signal.confidence,
                allocation_inr=allocation.allocation_inr,
                risk_percent=allocation.risk_percent,
                market_regime=market_regime,
                status=status,
                rejection_reasons=rejection_reasons,
                rejection_detail=rejection_detail,
                contributors=signal.contributors,
                timeframe=signal.timeframe,
                net_score=signal.net_score,
                agreement_ratio=signal.agreement_ratio,
                portfolio_id=pid or None,
                correlation_id=correlation_id,
                signal_timestamp=signal.timestamp,
                created_at=datetime.now(timezone.utc),
            )

            # ── 6. Metrics ────────────────────────────────────────────────────
            elapsed = time.perf_counter() - t0
            ORCHESTRATION_LATENCY.labels(symbol=signal.symbol).observe(elapsed)
            ELIGIBILITY_CHECKS.labels(symbol=signal.symbol, status=status.value).inc()
            for reason in rejection_reasons:
                REJECTION_REASONS.labels(symbol=signal.symbol, reason=reason.value).inc()
            if status == IntentStatus.ELIGIBLE:
                ALLOCATION_INR.labels(symbol=signal.symbol).observe(allocation.allocation_inr)

            span.set_attribute("intent_status", status.value)
            span.set_attribute("intent_id", intent.intent_id)
            span.set_attribute("allocation_inr", allocation.allocation_inr)
            span.set_attribute("elapsed_s", round(elapsed, 4))

            log.info(
                "intent_generated",
                symbol=signal.symbol,
                intent_id=intent.intent_id,
                status=status.value,
                confidence=signal.confidence,
                allocation_inr=allocation.allocation_inr,
                market_regime=market_regime,
                rejection_reasons=[r.value for r in rejection_reasons],
                elapsed_s=round(elapsed, 4),
            )

            return intent, checks, portfolio, risk

    async def _fetch_state(
        self, portfolio_id: str
    ) -> tuple[PortfolioState, RiskState]:
        from asyncio import gather

        portfolio_task = self._fetcher.get_portfolio_state(portfolio_id)
        risk_task = self._fetcher.get_risk_state(portfolio_id)
        portfolio, risk = await gather(portfolio_task, risk_task)

        # Safe defaults if fetch failed completely
        if portfolio is None:
            from datetime import datetime, timezone
            log.error("portfolio_state_unavailable", portfolio_id=portfolio_id)
            portfolio = PortfolioState(
                portfolio_id=portfolio_id,
                total_value_inr=0.0,
                cash_inr=0.0,
                equity_inr=0.0,
                day_pnl_inr=0.0,
                total_pnl_inr=0.0,
                positions=[],
                as_of=datetime.now(timezone.utc),
            )

        if risk is None:
            from datetime import datetime, timezone
            log.error("risk_state_unavailable", portfolio_id=portfolio_id)
            risk = RiskState(
                portfolio_id=portfolio_id,
                daily_loss_inr=0.0,
                daily_loss_limit_inr=settings.DAILY_LOSS_LIMIT_INR,
                drawdown_pct=0.0,
                max_drawdown_pct=settings.MAX_PORTFOLIO_DRAWDOWN_PCT,
                kill_switch_active=False,
                open_intents_count=0,
                correlation_matrix={},
                as_of=datetime.now(timezone.utc),
            )

        return portfolio, risk
