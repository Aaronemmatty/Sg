"""
Unit tests for the Pre-Trade Transaction Cost Gate.

Tests:
  1. Cost breakdown accuracy (Zerodha retail equity intraday: brokerage, slippage, STT,
     exchange txn charges, GST, stamp duty).
  2. Signal clearly clears the cost hurdle and publishes.
  3. Signal clearly fails the cost hurdle and is suppressed from publishing.
  4. Edge cases near the 33.33% hurdle threshold (just above passes, just below gets suppressed).
  5. HOLD signals are not suppressed.
  6. Extraction of expected move from take_profit / entry_price, metadata, and top-level fields.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.core.cost_gate import (
    CostGateEngine,
    estimate_round_trip_cost,
    extract_expected_move,
)
from app.core.engine import SignalAggregationEngine
from app.models.domain import AggregatedSignalResult, RegimeRef, SignalAction
from tests.conftest import make_raw_signal


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    return session


def test_estimate_round_trip_cost_breakdown(settings: Settings):
    # Test at 20% position sizing on ₹9,000 capital = ₹1,800
    notional = 1800.0
    cost = estimate_round_trip_cost(notional, settings)

    assert cost.notional_inr == 1800.0

    # 1. Brokerage: min(20, 1800 * 0.0003) = 0.54 per leg -> 1.08 round trip
    assert cost.brokerage_inr == pytest.approx(1.08, abs=1e-3)

    # 2. Slippage: 2 * 1800 * 0.0005 = 1.80 round trip
    assert cost.slippage_inr == pytest.approx(1.80, abs=1e-3)

    # 3. STT: 1800 * 0.00025 (sell leg) = 0.45
    assert cost.stt_inr == pytest.approx(0.45, abs=1e-3)

    # 4. Exchange txn: 2 * 1800 * 0.0000345 = 0.1242
    assert cost.exchange_txn_inr == pytest.approx(0.1242, abs=1e-4)

    # 5. Stamp duty: 1800 * 0.00015 (buy leg) = 0.27
    assert cost.stamp_duty_inr == pytest.approx(0.27, abs=1e-3)

    # 6. GST: 18% on (1.08 + 0.1242) = 0.216756
    expected_gst = 0.18 * (1.08 + 0.1242)
    assert cost.gst_inr == pytest.approx(expected_gst, abs=1e-3)

    # Total round-trip cost = 1.08 + 1.80 + 0.45 + 0.1242 + 0.27 + 0.2168 = ~3.941
    expected_total = 1.08 + 1.80 + 0.45 + 0.1242 + 0.27 + expected_gst
    assert cost.total_round_trip_cost_inr == pytest.approx(expected_total, abs=1e-3)
    assert cost.round_trip_cost_pct == pytest.approx(expected_total / 1800.0, abs=1e-5)


@pytest.mark.asyncio
async def test_signal_clears_cost_hurdle_and_publishes(settings: Settings, mock_session):
    """
    Case 1: Strategy expects a 1.5% gross move (₹27.00 profit on ₹1,800).
    Round-trip cost is ~₹3.94 (14.6% of move <= 33.3% hurdle).
    Must PASS the cost gate and PUBLISH to Redis.
    """
    raw_signals = {
        "trend_following": {
            **make_raw_signal("trend_following", action="BUY", confidence=0.85),
            "expected_move_pct": 0.015,  # 1.5% expected move
        },
        "breakout": {
            **make_raw_signal("breakout", action="BUY", confidence=0.80),
            "expected_move_pct": 0.015,
        },
    }

    mock_redis = MagicMock()
    mock_redis.collect_all_raw_signals = AsyncMock(return_value=raw_signals)
    mock_redis.get_regime = AsyncMock(
        return_value=RegimeRef(regime="TRENDING", confidence=0.9, timestamp=datetime.now(timezone.utc))
    )
    mock_redis.set_cached_result = AsyncMock()
    mock_redis.publish_result = AsyncMock()

    mock_weight_store = MagicMock()
    mock_weight_store.refresh = AsyncMock()
    mock_weight_store.get_overrides = MagicMock(return_value={})

    engine = SignalAggregationEngine(settings, mock_redis, mock_weight_store)
    result = await engine.aggregate(mock_session, "RELIANCE", "5m")

    assert result.final_signal == SignalAction.BUY
    assert result.cost_gate_passed is True
    assert result.is_published is True
    assert result.cost_gate_details is not None
    assert result.cost_gate_details["passed"] is True
    assert result.cost_gate_details["suppressed"] is False
    assert result.cost_gate_details["cost_to_move_ratio"] < 0.3333

    # Confirm publication occurred
    mock_redis.publish_result.assert_awaited_once_with(result)


@pytest.mark.asyncio
async def test_signal_fails_cost_hurdle_and_gets_suppressed(settings: Settings, mock_session):
    """
    Case 2: Strategy expects a 0.3% move (₹5.40 profit on ₹1,800).
    Round-trip cost of ~₹3.94 consumes 73% of the move (> 33.3% hurdle).
    Must FAIL the cost gate and be SUPPRESSED from publishing.
    """
    raw_signals = {
        "trend_following": {
            **make_raw_signal("trend_following", action="BUY", confidence=0.85),
            "expected_move_pct": 0.003,  # Only 0.3% expected move
        },
        "breakout": {
            **make_raw_signal("breakout", action="BUY", confidence=0.80),
            "expected_move_pct": 0.003,
        },
    }

    mock_redis = MagicMock()
    mock_redis.collect_all_raw_signals = AsyncMock(return_value=raw_signals)
    mock_redis.get_regime = AsyncMock(
        return_value=RegimeRef(regime="TRENDING", confidence=0.9, timestamp=datetime.now(timezone.utc))
    )
    mock_redis.set_cached_result = AsyncMock()
    mock_redis.publish_result = AsyncMock()

    mock_weight_store = MagicMock()
    mock_weight_store.refresh = AsyncMock()
    mock_weight_store.get_overrides = MagicMock(return_value={})

    engine = SignalAggregationEngine(settings, mock_redis, mock_weight_store)
    result = await engine.aggregate(mock_session, "RELIANCE", "5m")

    assert result.final_signal == SignalAction.BUY
    assert result.cost_gate_passed is False
    assert result.is_published is False
    assert result.cost_gate_details is not None
    assert result.cost_gate_details["passed"] is False
    assert result.cost_gate_details["suppressed"] is True
    assert result.cost_gate_details["cost_to_move_ratio"] > 0.3333

    # Confirm result was cached and saved, but NOT published to Redis pub/sub
    mock_redis.set_cached_result.assert_awaited_once_with(result)
    mock_session.add.assert_called_once()
    mock_redis.publish_result.assert_not_called()


def test_edge_cases_near_threshold(settings: Settings):
    """
    Case 3: Edge cases near the 33.33% threshold.
    For ₹1,800 position with ~₹3.941 cost:
    Threshold move = 3.9410 / 0.3333 = ₹11.824 (0.6569%).
      - Sub-case 3A: 0.68% move (₹12.24) -> cost_ratio ~32.2% <= 33.33% -> PASSES.
      - Sub-case 3B: 0.64% move (₹11.52) -> cost_ratio ~34.2% > 33.33% -> SUPPRESSED.
    """
    gate = CostGateEngine(settings)

    # 3A: Just above threshold (0.68%)
    raw_pass = {
        "momentum": {"expected_move_pct": 0.0068}
    }
    decision_pass = gate.evaluate("RELIANCE", SignalAction.BUY, raw_pass, ["momentum"])
    assert decision_pass.passed is True
    assert decision_pass.suppressed is False
    assert decision_pass.cost_to_move_ratio <= settings.COST_GATE_MAX_COST_TO_MOVE_RATIO

    # 3B: Just below threshold (0.64%)
    raw_fail = {
        "momentum": {"expected_move_pct": 0.0064}
    }
    decision_fail = gate.evaluate("RELIANCE", SignalAction.BUY, raw_fail, ["momentum"])
    assert decision_fail.passed is False
    assert decision_fail.suppressed is True
    assert decision_fail.cost_to_move_ratio > settings.COST_GATE_MAX_COST_TO_MOVE_RATIO


def test_hold_signal_not_suppressed(settings: Settings):
    gate = CostGateEngine(settings)
    raw = {"trend_following": {"expected_move_pct": 0.001}}
    decision = gate.evaluate("RELIANCE", SignalAction.HOLD, raw, ["trend_following"])
    assert decision.passed is True
    assert decision.suppressed is False


def test_extract_expected_move_formats():
    # Format 1: take_profit and entry_price
    raw_tp = {
        "s1": {"entry_price": 2500.0, "take_profit": 2550.0}  # (2550 - 2500)/2500 = 2.0%
    }
    assert extract_expected_move(raw_tp, ["s1"]) == pytest.approx(0.02)

    # Format 2: metadata dict
    raw_meta = {
        "s2": {"metadata": {"expected_move": 0.018}}
    }
    assert extract_expected_move(raw_meta, ["s2"]) == pytest.approx(0.018)

    # Format 3: percentage representation > 0.5 (e.g. 1.25 meaning 1.25%)
    raw_pct = {
        "s3": {"expected_return": 1.25}
    }
    assert extract_expected_move(raw_pct, ["s3"]) == pytest.approx(0.0125)
