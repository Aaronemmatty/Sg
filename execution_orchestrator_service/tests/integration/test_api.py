"""Integration tests — API endpoints."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.models.domain import (
    AggregatedSignal,
    IntentStatus,
    TradeAction,
    TradeIntent,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_intent():
    return TradeIntent(
        intent_id="test-intent-001",
        correlation_id="corr-001",
        symbol="RELIANCE",
        action=TradeAction.BUY,
        confidence=0.82,
        allocation_inr=45_000.0,
        risk_percent=1.2,
        market_regime="TRENDING",
        status=IntentStatus.ELIGIBLE,
        rejection_reasons=[],
        contributors=["rsi_strategy"],
        timeframe="1D",
        portfolio_id="port-001",
        created_at=datetime.now(timezone.utc),
        signal_timestamp=datetime.now(timezone.utc),
    )


@pytest.fixture
def mock_rejected_intent():
    from app.models.domain import RejectionReason
    return TradeIntent(
        intent_id="test-intent-002",
        correlation_id="corr-002",
        symbol="NIFTY",
        action=TradeAction.BUY,
        confidence=0.45,
        allocation_inr=0.0,
        risk_percent=0.0,
        market_regime="VOLATILE",
        status=IntentStatus.REJECTED,
        rejection_reasons=[RejectionReason.LOW_CONFIDENCE],
        rejection_detail="confidence=0.450 < threshold=0.600",
        created_at=datetime.now(timezone.utc),
    )


# ── Health endpoints ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_ok():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "execution-orchestrator"


@pytest.mark.asyncio
async def test_config_endpoint():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "min_confidence" in data
    assert "max_allocation_pct" in data
    assert "min_liquidity_pct" in data
    assert data["min_confidence"] == pytest.approx(0.60, abs=0.01)



# ── Intent endpoints ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_intents_empty(mock_db_session):
    """list_intents returns empty list with proper meta when no records."""
    with patch("app.api.v1.endpoints.intents.IntentRepository") as MockRepo:
        mock_repo = MagicMock()
        mock_repo.list_intents = AsyncMock(return_value=([], 0))
        MockRepo.return_value = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/intents")

    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_get_intent_not_found(mock_db_session):
    with patch("app.api.v1.endpoints.intents.IntentRepository") as MockRepo:
        mock_repo = MagicMock()
        mock_repo.get_by_intent_id = AsyncMock(return_value=None)
        MockRepo.return_value = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/intents/nonexistent-id")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_manual_inject_produces_intent(mock_intent):
    with patch("app.api.v1.endpoints.intents.get_orchestrator_service") as mock_svc_fn, \
         patch("app.api.v1.endpoints.intents.IntentRepository") as MockRepo:

        svc = MagicMock()
        svc.handle_signal = AsyncMock(return_value=mock_intent)
        mock_svc_fn.return_value = svc

        mock_repo = MagicMock()
        mock_repo.get_by_intent_id = AsyncMock(return_value=None)  # triggers domain fallback
        MockRepo.return_value = mock_repo

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/intents",
                json={
                    "symbol": "RELIANCE",
                    "action": "BUY",
                    "confidence": 0.82,
                    "timeframe": "1D",
                },
            )

    assert resp.status_code == 201
    data = resp.json()
    assert data["symbol"] == "RELIANCE"
    assert data["status"] == "ELIGIBLE"
    assert data["intent_id"] == "test-intent-001"


@pytest.mark.asyncio
async def test_manual_inject_validates_confidence():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/intents",
            json={
                "symbol": "NIFTY",
                "action": "BUY",
                "confidence": 1.5,   # > 1.0 — invalid
            },
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_manual_inject_validates_action():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/intents",
            json={
                "symbol": "NIFTY",
                "action": "MAYBE",   # invalid
                "confidence": 0.75,
            },
        )
    assert resp.status_code == 422


# ── Conftest helpers (inline for self-contained test file) ────────────────────

@pytest.fixture
def mock_db_session():
    """Patch get_db dependency to return a no-op session."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def _override():
        yield mock_session

    app.dependency_overrides[__import__(
        "app.db.session", fromlist=["get_db"]
    ).get_db] = _override
    yield mock_session
    app.dependency_overrides.clear()
