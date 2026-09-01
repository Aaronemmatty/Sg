"""Unit tests — eligibility engine."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.domain import (
    AggregatedSignal,
    MarketRegime,
    PortfolioState,
    PositionSnapshot,
    RiskState,
    RejectionReason,
    TradeAction,
)
from app.orchestrator.eligibility import (
    check_confidence,
    check_correlation,
    check_daily_loss,
    check_drawdown,
    check_liquidity,
    check_open_intents,
    check_position_limit,
    check_sector_exposure,
    run_all_checks,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _signal(
    symbol="RELIANCE",
    action=TradeAction.BUY,
    confidence=0.80,
    regime="TRENDING",
) -> AggregatedSignal:
    return AggregatedSignal(
        symbol=symbol,
        timeframe="1D",
        final_signal=action,
        confidence=confidence,
        contributors=["rsi_strategy"],
        regime=regime,
        timestamp=datetime.now(timezone.utc),
    )


def _portfolio(
    total_value=1_000_000.0,
    cash=500_000.0,
    positions: list[PositionSnapshot] | None = None,
) -> PortfolioState:
    return PortfolioState(
        portfolio_id="port-001",
        total_value_inr=total_value,
        cash_inr=cash,
        equity_inr=total_value - cash,
        day_pnl_inr=0.0,
        total_pnl_inr=0.0,
        positions=positions or [],
        as_of=datetime.now(timezone.utc),
    )


def _risk(
    daily_loss=0.0,
    daily_limit=50_000.0,
    drawdown=0.0,
    max_drawdown=0.15,
    kill_switch=False,
    open_intents=0,
    correlation_matrix: dict | None = None,
) -> RiskState:
    return RiskState(
        portfolio_id="port-001",
        daily_loss_inr=daily_loss,
        daily_loss_limit_inr=daily_limit,
        drawdown_pct=drawdown,
        max_drawdown_pct=max_drawdown,
        kill_switch_active=kill_switch,
        open_intents_count=open_intents,
        correlation_matrix=correlation_matrix or {},
        as_of=datetime.now(timezone.utc),
    )


# ── Confidence ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confidence_passes():
    result = await check_confidence(_signal(confidence=0.75))
    assert result.passed is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_confidence_fails_below_threshold():
    result = await check_confidence(_signal(confidence=0.50))
    assert result.passed is False
    assert result.reason == RejectionReason.LOW_CONFIDENCE


@pytest.mark.asyncio
async def test_confidence_exact_threshold():
    with patch("app.orchestrator.eligibility.settings") as m:
        m.MIN_CONFIDENCE = 0.60
        result = await check_confidence(_signal(confidence=0.60))
    assert result.passed is True


# ── Liquidity ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_liquidity_passes():
    result = await check_liquidity(_signal(), _portfolio(cash=200_000.0))
    assert result.passed is True


@pytest.mark.asyncio
async def test_liquidity_fails():
    result = await check_liquidity(_signal(), _portfolio(cash=50.0))
    assert result.passed is False
    assert result.reason == RejectionReason.LIQUIDITY_VIOLATION


# ── Position limit ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_position_limit_no_existing_position():
    result = await check_position_limit(_signal(), _portfolio())
    assert result.passed is True


@pytest.mark.asyncio
async def test_position_limit_under_threshold():
    pos = PositionSnapshot(symbol="RELIANCE", weight_pct=0.05)
    result = await check_position_limit(_signal(), _portfolio(positions=[pos]))
    assert result.passed is True


@pytest.mark.asyncio
async def test_position_limit_over_threshold():
    pos = PositionSnapshot(symbol="RELIANCE", weight_pct=0.12)  # > 10%
    result = await check_position_limit(_signal(), _portfolio(positions=[pos]))
    assert result.passed is False
    assert result.reason == RejectionReason.POSITION_LIMIT


@pytest.mark.asyncio
async def test_position_limit_skipped_for_sell():
    pos = PositionSnapshot(symbol="RELIANCE", weight_pct=0.50)  # huge position
    result = await check_position_limit(
        _signal(action=TradeAction.SELL), _portfolio(positions=[pos])
    )
    assert result.passed is True  # SELL is never blocked by position limit


# ── Sector exposure ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sector_exposure_no_sector_skips():
    pos = PositionSnapshot(symbol="RELIANCE", sector=None, current_value_inr=500_000)
    result = await check_sector_exposure(_signal(), _portfolio(positions=[pos]))
    assert result.passed is True


@pytest.mark.asyncio
async def test_sector_exposure_within_limit():
    pos = PositionSnapshot(
        symbol="RELIANCE", sector="ENERGY", current_value_inr=200_000
    )
    port = _portfolio(total_value=1_000_000.0, positions=[pos])
    result = await check_sector_exposure(_signal(), port)
    assert result.passed is True


@pytest.mark.asyncio
async def test_sector_exposure_exceeded():
    pos = PositionSnapshot(
        symbol="RELIANCE", sector="ENERGY", current_value_inr=350_000
    )
    port = _portfolio(total_value=1_000_000.0, positions=[pos])
    result = await check_sector_exposure(_signal(), port)
    assert result.passed is False
    assert result.reason == RejectionReason.EXCESS_EXPOSURE


# ── Correlation ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_correlation_no_matrix_passes():
    result = await check_correlation(_signal(), _risk(), _portfolio())
    assert result.passed is True


@pytest.mark.asyncio
async def test_correlation_below_threshold_passes():
    pos = PositionSnapshot(symbol="TCS", weight_pct=0.10, current_value_inr=100_000)
    port = _portfolio(positions=[pos])
    matrix = {"RELIANCE": {"TCS": 0.65}}
    risk = _risk(correlation_matrix=matrix)
    result = await check_correlation(_signal(), risk, port)
    assert result.passed is True


@pytest.mark.asyncio
async def test_correlation_violation():
    pos = PositionSnapshot(symbol="TCS", weight_pct=0.10, current_value_inr=100_000)
    port = _portfolio(positions=[pos])
    matrix = {"RELIANCE": {"TCS": 0.92}}
    risk = _risk(correlation_matrix=matrix)
    result = await check_correlation(_signal(), risk, port)
    assert result.passed is False
    assert result.reason == RejectionReason.CORRELATION_VIOLATION


# ── Daily loss ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_loss_ok():
    result = await check_daily_loss(_risk(daily_loss=10_000, daily_limit=50_000))
    assert result.passed is True


@pytest.mark.asyncio
async def test_daily_loss_exceeded():
    result = await check_daily_loss(_risk(daily_loss=55_000, daily_limit=50_000))
    assert result.passed is False
    assert result.reason == RejectionReason.DAILY_LOSS_LIMIT


@pytest.mark.asyncio
async def test_kill_switch_blocks_all():
    result = await check_daily_loss(_risk(kill_switch=True))
    assert result.passed is False
    assert result.reason == RejectionReason.DAILY_LOSS_LIMIT


# ── Drawdown ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_drawdown_ok():
    result = await check_drawdown(_risk(drawdown=0.05, max_drawdown=0.15))
    assert result.passed is True


@pytest.mark.asyncio
async def test_drawdown_exceeded():
    result = await check_drawdown(_risk(drawdown=0.20, max_drawdown=0.15))
    assert result.passed is False
    assert result.reason == RejectionReason.DRAWDOWN_LIMIT


# ── Open intents ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_intents_ok():
    result = await check_open_intents(_risk(open_intents=2))
    assert result.passed is True



@pytest.mark.asyncio
async def test_open_intents_at_max():
    with patch("app.orchestrator.eligibility.settings") as m:
        m.MAX_OPEN_INTENTS = 10
        result = await check_open_intents(_risk(open_intents=10))
    assert result.passed is False
    assert result.reason == RejectionReason.MAX_OPEN_INTENTS


# ── Pipeline — run_all_checks ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_all_checks_all_pass():
    signal = _signal(confidence=0.85)
    portfolio = _portfolio(cash=500_000)
    risk = _risk()
    results = await run_all_checks(signal, portfolio, risk)
    assert len(results) == 8
    assert all(r.passed for r in results)


@pytest.mark.asyncio
async def test_run_all_checks_does_not_short_circuit():
    """All checks run even if confidence fails."""
    signal = _signal(confidence=0.20)   # will fail confidence
    portfolio = _portfolio(cash=50)     # will also fail liquidity
    risk = _risk(daily_loss=60_000)     # will also fail daily_loss
    results = await run_all_checks(signal, portfolio, risk)
    assert len(results) == 8            # all 8 checks ran
    failed = [r for r in results if not r.passed]
    assert len(failed) >= 3


@pytest.mark.asyncio
async def test_hold_signal_passes_all_positional_checks():
    """A HOLD signal should pass position/sector/correlation checks."""
    signal = _signal(action=TradeAction.HOLD, confidence=0.90)
    results = await run_all_checks(signal, _portfolio(), _risk())
    position_result = next(r for r in results if r.check_name == "position_limit")
    assert position_result.passed is True
