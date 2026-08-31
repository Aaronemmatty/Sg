from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import app.main as main_module


@pytest.fixture
async def api():
    """Yields (client, mocks) with all I/O bypassed by populating app.state
    directly instead of running the FastAPI lifespan — same pattern used
    across the platform's integration tests."""
    app = main_module.app

    mocks = {
        "db_pool": MagicMock(),
        "repo": AsyncMock(),
        "prompt_manager": AsyncMock(),
        "analysis_service": AsyncMock(),
        "portfolio_client": AsyncMock(),
        "risk_client": AsyncMock(),
        "execution_client": AsyncMock(),
        "market_data_client": AsyncMock(),
    }

    for name, mock in mocks.items():
        setattr(app.state, name, mock)

    # PromptManager.invalidate() is a synchronous method on the real class —
    # override the AsyncMock default so admin.py's unawaited call behaves
    # the same way it would for real, with no "never awaited" warning.
    mocks["prompt_manager"].invalidate = MagicMock()

    # Sensible defaults so context builders don't choke on unset mocks.
    mocks["portfolio_client"].get_snapshot.return_value = {"available": True, "data": {}}
    mocks["portfolio_client"].get_exposure.return_value = {"available": True, "data": {}}
    mocks["portfolio_client"].get_positions.return_value = {"available": True, "data": []}
    mocks["portfolio_client"].get_recent_trades.return_value = {"available": True, "data": []}
    mocks["portfolio_client"].get_performance.return_value = {"available": True, "data": {}}
    mocks["execution_client"].get_recent_orders.return_value = {"available": True, "data": []}
    mocks["risk_client"].get_risk_snapshot.return_value = {"available": True, "data": {}}
    mocks["risk_client"].get_recent_risk_events.return_value = {"available": True, "data": []}
    mocks["market_data_client"].get_ltp.return_value = {"available": True, "data": {"ltp": 100.0}}
    mocks["market_data_client"].get_recent_history.return_value = {"available": True, "data": {}}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, mocks
