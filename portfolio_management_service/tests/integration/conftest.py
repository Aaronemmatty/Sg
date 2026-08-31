"""
Integration test fixtures for portfolio_management_service (8009).

Strategy:
  - Import app.main FIRST so the module exists before any patch targets it.
  - Patch all I/O dependencies (DB pool, Redis, background tasks, OTel) at
    function scope so each test gets a clean slate.
  - Provide an httpx.AsyncClient wired to the FastAPI app via ASGITransport.

All patches target the exact dotted paths used inside each module, not
the originating module, matching Python mock best-practice.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ── Force eager import of app.main so submodule attributes exist ─────────────
import os
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost/x")

# Stub out OTel exporter before main imports it (avoids gRPC connect)
with patch("opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter.__init__",
           return_value=None):
    import app.main  # noqa: F401 — side-effect: registers submodules


@pytest_asyncio.fixture
async def client():
    """
    AsyncClient bound to the FastAPI app.

    Patches all I/O at function scope:
      - asyncpg pool (init + close + acquire)
      - Redis (connect + close + pubsub)
      - Background loop coroutines (mtm, snapshot, consumer)
      - Market data client close
      - OTel tracing (already stubbed at import time)
    """
    from httpx import ASGITransport, AsyncClient

    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=1)
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_pool.close = AsyncMock()

    mock_redis = AsyncMock()
    mock_pubsub = AsyncMock()
    mock_pubsub.psubscribe = AsyncMock()
    mock_pubsub.close = AsyncMock()
    mock_redis.pubsub = MagicMock(return_value=mock_pubsub)
    mock_redis.ping = AsyncMock()
    mock_redis.close = AsyncMock()
    mock_redis.publish = AsyncMock()

    # A stop_event that immediately triggers so background loops exit fast
    stop_event = asyncio.Event()
    stop_event.set()

    patches = [
        patch("app.db.session.init_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("app.db.session.close_pool", new_callable=AsyncMock),
        patch("app.db.session.pool", mock_pool),
        patch("app.core.redis.get_redis", new_callable=AsyncMock, return_value=mock_redis),
        patch("app.core.redis.close_redis", new_callable=AsyncMock),
        patch("app.core.redis._client", mock_redis),
        patch("app.publishers.portfolio_publisher._redis_client", mock_redis),
        patch(
            "app.services.market_data_client.market_data_client.aclose",
            new_callable=AsyncMock,
        ),
        # Prevent real DB migration on startup
        patch("app.db.session._run_migrations", new_callable=AsyncMock),
        # Kill background tasks immediately
        patch("app.main._mtm_refresh_loop", new_callable=AsyncMock),
        patch("app.main._snapshot_loop", new_callable=AsyncMock),
        patch(
            "app.consumers.execution_consumer.ExecutionConsumer.run",
            new_callable=AsyncMock,
        ),
        patch(
            "app.consumers.execution_consumer.ExecutionConsumer.shutdown",
            new_callable=AsyncMock,
        ),
    ]

    started = [p.start() for p in patches]

    async with AsyncClient(
        transport=ASGITransport(app=app.main.app),
        base_url="http://test",
    ) as c:
        yield c

    for p in patches:
        p.stop()
