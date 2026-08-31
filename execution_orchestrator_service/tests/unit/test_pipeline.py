"""Unit tests — OrchestratorPipeline."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.domain import (
    AggregatedSignal,
    IntentStatus,
    MarketRegime,
    PortfolioState,
    RiskState,
    TradeAction,
    TradeIntent,
)
from app.orchestrator.pipeline import OrchestratorPipeline


def _signal(action=TradeAction.BUY, confidence=0.85, regime="TRENDING") -> AggregatedSignal:
    return AggregatedSignal(
        symbol="NIFTY",
        timeframe="1D",
        final_signal=action,
        confidence=confidence,
        contributors=["momentum"],
        regime=regime,
        timestamp=datetime.now(timezone.utc),
    )


def _portfolio(total=1_000_000.0, cash=600_000.0) -> PortfolioState:
    return PortfolioState(
        portfolio_id="port-001",
        total_value_inr=total,
        cash_inr=cash,
        equity_inr=total - cash,
        day_pnl_inr=0.0,
        total_pnl_inr=0.0,
        positions=[],
        as_of=datetime.now(timezone.utc),
    )


def _risk() -> RiskState:
    return RiskState(
        portfolio_id="port-001",
        daily_loss_inr=0.0,
        daily_loss_limit_inr=50_000.0,
        drawdown_pct=0.0,
        max_drawdown_pct=0.15,
        kill_switch_active=False,
        open_intents_count=0,
        correlation_matrix={},
        as_of=datetime.now(timezone.utc),
    )


def _make_pipeline(portfolio=None, risk=None, regime_cache=None):
    fetcher = MagicMock()
    fetcher.get_portfolio_state = AsyncMock(return_value=portfolio or _portfolio())
    fetcher.get_risk_state = AsyncMock(return_value=risk or _risk())
    return OrchestratorPipeline(
        state_fetcher=fetcher,
        regime_cache=regime_cache or {},
    )


@pytest.mark.asyncio
async def test_eligible_signal_produces_eligible_intent():
    pipeline = _make_pipeline()
    intent, checks, portfolio, risk = await pipeline.process(_signal(), "port-001")

    assert intent.status == IntentStatus.ELIGIBLE
    assert intent.symbol == "NIFTY"
    assert intent.action == TradeAction.BUY
    assert intent.allocation_inr > 0
    assert len(intent.rejection_reasons) == 0


@pytest.mark.asyncio
async def test_hold_action_produces_hold_intent():
    pipeline = _make_pipeline()
    intent, checks, _, _ = await pipeline.process(_signal(action=TradeAction.HOLD))
    assert intent.status == IntentStatus.HOLD


@pytest.mark.asyncio
async def test_low_confidence_produces_rejected_intent():
    pipeline = _make_pipeline()
    intent, checks, _, _ = await pipeline.process(_signal(confidence=0.30))
    assert intent.status == IntentStatus.REJECTED
    from app.models.domain import RejectionReason
    assert RejectionReason.LOW_CONFIDENCE in intent.rejection_reasons


@pytest.mark.asyncio
async def test_kill_switch_produces_rejected():
    risk = _risk()
    risk.kill_switch_active = True
    pipeline = _make_pipeline(risk=risk)
    intent, _, _, _ = await pipeline.process(_signal(confidence=0.90))
    assert intent.status == IntentStatus.REJECTED
    from app.models.domain import RejectionReason
    assert RejectionReason.DAILY_LOSS_LIMIT in intent.rejection_reasons


@pytest.mark.asyncio
async def test_regime_resolved_from_signal():
    pipeline = _make_pipeline(regime_cache={})
    intent, _, _, _ = await pipeline.process(_signal(regime="VOLATILE"))
    assert intent.market_regime == "VOLATILE"


@pytest.mark.asyncio
async def test_regime_resolved_from_cache_when_signal_has_none():
    cache = {"NIFTY": "MEAN_REVERTING"}
    pipeline = _make_pipeline(regime_cache=cache)

    sig = _signal()
    sig.regime = None   # no regime in signal
    intent, _, _, _ = await pipeline.process(sig)
    assert intent.market_regime == "MEAN_REVERTING"


@pytest.mark.asyncio
async def test_intent_has_all_required_fields():
    pipeline = _make_pipeline()
    intent, _, _, _ = await pipeline.process(_signal())

    assert intent.intent_id
    assert intent.correlation_id
    assert intent.created_at is not None
    assert intent.signal_timestamp is not None
    assert intent.timeframe == "1D"


@pytest.mark.asyncio
async def test_daily_loss_exceeded_produces_rejected():
    risk = _risk()
    risk.daily_loss_inr = 60_000.0   # > 50_000 limit
    pipeline = _make_pipeline(risk=risk)
    intent, _, _, _ = await pipeline.process(_signal(confidence=0.90))
    assert intent.status == IntentStatus.REJECTED


@pytest.mark.asyncio
async def test_zero_portfolio_allocation_still_eligible_or_rejected_by_allocation():
    """Zero portfolio should produce zero allocation → REJECTED allocation_too_small."""
    portfolio = _portfolio(total=0.0, cash=0.0)
    pipeline = _make_pipeline(portfolio=portfolio)
    intent, _, _, _ = await pipeline.process(_signal(confidence=0.90))
    # Either rejected for allocation_too_small or liquidity
    assert intent.status == IntentStatus.REJECTED
