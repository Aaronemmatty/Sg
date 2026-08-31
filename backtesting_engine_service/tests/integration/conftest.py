from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import app.main as main_module


@pytest.fixture
async def api():
    """Yields (async_client, mock_job_manager, mock_repo) with real DB/network
    fully bypassed — app.state is populated directly instead of running the
    FastAPI lifespan, matching the established integration test pattern of
    patching all I/O at function scope inside the client fixture."""
    app = main_module.app

    mock_pool = MagicMock()
    mock_repo = AsyncMock()
    mock_job_manager = AsyncMock()
    mock_job_manager.repo = mock_repo

    app.state.db_pool = mock_pool
    app.state.job_manager = mock_job_manager

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, mock_job_manager, mock_repo
