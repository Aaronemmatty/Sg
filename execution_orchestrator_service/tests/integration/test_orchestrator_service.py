"""Integration tests — OrchestratorService end-to-end."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.domain import (
    AggregatedSignal,
    IntentStatus,
    PortfolioState,
    RiskState,
    TradeAction,
)
from app.services.orchestrator_service import OrchestratorService


def _signal(confidence=0.82, action=TradeAction.BUY, regime="TRENDING") -> AggregatedSignal:
    return AggregatedSignal(
        symbol="HDFC",
        timeframe="1D",
        final_signal=action,
        confidence=confidence,
        contributors=["bollinger", "rsi"],
        regime=regime,
        timestamp=datetime.now(timezone.utc),
    )


def _portfolio() -> PortfolioState:
    return PortfolioState(
        portfolio_id="port-001",
        total_value_inr=2_000_000.0,
        cash_inr=1_200_000.0,
        equity_inr=800_000.0,
        day_pnl_inr=5_000.0,
        total_pnl_inr=20_000.0,
        positions=[],
        as_of=datetime.now(timezone.utc),
    )


def _risk() -> RiskState:
    return RiskState(
        portfolio_id="port-001",
        daily_loss_inr=2_000.0,
        daily_loss_limit_inr=50_000.0,
        drawdown_pct=0.02,
        max_drawdown_pct=0.15,
        kill_switch_active=False,
        open_intents_count=3,
        correlation_matrix={},
        as_of=datetime.now(timezone.utc),
    )


def _make_service() -> tuple[OrchestratorService, dict]:
    regime_cache: dict[str, str] = {}
    svc = OrchestratorService(regime_cache=regime_cache)
    return svc, regime_cache


@pytest.mark.asyncio
async def test_eligible_signal_full_pipeline():
    svc, _ = _make_service()

    with patch.object(svc._fetcher, "get_portfolio_state", AsyncMock(return_value=_portfolio())), \
         patch.object(svc._fetcher, "get_risk_state", AsyncMock(return_value=_risk())), \
         patch.object(svc._publisher, "publish", AsyncMock()) as mock_publish:

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db.add_all = MagicMock()

        # Stub repository
        with patch("app.services.orchestrator_service.IntentRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.persist_intent = AsyncMock()
            mock_repo.persist_audit_checks = AsyncMock()
            MockRepo.return_value = mock_repo

            intent = await svc.handle_signal(signal=_signal(), db=db)

    assert intent.status == IntentStatus.ELIGIBLE
    assert intent.symbol == "HDFC"
    assert intent.allocation_inr > 0
    mock_publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_rejected_signal_still_persisted_and_published():
    svc, _ = _make_service()

    risk = _risk()
    risk.kill_switch_active = True

    with patch.object(svc._fetcher, "get_portfolio_state", AsyncMock(return_value=_portfolio())), \
         patch.object(svc._fetcher, "get_risk_state", AsyncMock(return_value=risk)), \
         patch.object(svc._publisher, "publish", AsyncMock()) as mock_publish:

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        with patch("app.services.orchestrator_service.IntentRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.persist_intent = AsyncMock()
            mock_repo.persist_audit_checks = AsyncMock()
            MockRepo.return_value = mock_repo

            intent = await svc.handle_signal(signal=_signal(confidence=0.90), db=db)

    assert intent.status == IntentStatus.REJECTED
    # Even rejected intents are published so risk_engine can log/audit
    mock_publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_db_persist_failure_does_not_block_publish():
    """If DB write fails, intent must still be published (best-effort persistence)."""
    svc, _ = _make_service()

    with patch.object(svc._fetcher, "get_portfolio_state", AsyncMock(return_value=_portfolio())), \
         patch.object(svc._fetcher, "get_risk_state", AsyncMock(return_value=_risk())), \
         patch.object(svc._publisher, "publish", AsyncMock()) as mock_publish:

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        with patch("app.services.orchestrator_service.IntentRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.persist_intent = AsyncMock(side_effect=Exception("DB down"))
            mock_repo.persist_audit_checks = AsyncMock()
            MockRepo.return_value = mock_repo

            intent = await svc.handle_signal(signal=_signal(), db=db)

    # Publisher must still have been called
    mock_publish.assert_awaited_once()
    assert intent is not None


@pytest.mark.asyncio
async def test_regime_cache_used_when_signal_has_no_regime():
    svc, regime_cache = _make_service()
    regime_cache["HDFC"] = "MEAN_REVERTING"

    sig = _signal()
    sig.regime = None   # no regime in signal

    with patch.object(svc._fetcher, "get_portfolio_state", AsyncMock(return_value=_portfolio())), \
         patch.object(svc._fetcher, "get_risk_state", AsyncMock(return_value=_risk())), \
         patch.object(svc._publisher, "publish", AsyncMock()):

        db = MagicMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        with patch("app.services.orchestrator_service.IntentRepository") as MockRepo:
            mock_repo = MagicMock()
            mock_repo.persist_intent = AsyncMock()
            mock_repo.persist_audit_checks = AsyncMock()
            MockRepo.return_value = mock_repo

            intent = await svc.handle_signal(signal=sig, db=db)

    assert intent.market_regime == "MEAN_REVERTING"
