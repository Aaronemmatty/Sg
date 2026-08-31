"""
Integration test conftest for ml_platform_service (8011).

Same pattern as portfolio_management_service (8009) conftest:
  - Eager import of app.main before any patches
  - Function-scope patches for all I/O (DB, Redis, background tasks)
  - httpx.AsyncClient via ASGITransport
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

import os
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost/x")
os.environ.setdefault("MODEL_ARTIFACTS_PATH", "/tmp/ml_test_models")

# Stub OTel before import to avoid gRPC connect attempts
with patch(
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter.__init__",
    return_value=None,
):
    import app.main  # noqa: F401


@pytest_asyncio.fixture
async def client():
    """AsyncClient bound to the FastAPI app with all I/O patched."""
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
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()

    patches = [
        patch("app.db.session.init_pool", new_callable=AsyncMock, return_value=mock_pool),
        patch("app.db.session.close_pool", new_callable=AsyncMock),
        patch("app.db.session.pool", mock_pool),
        patch("app.db.session._run_migrations", new_callable=AsyncMock),
        patch("app.core.redis.get_redis", new_callable=AsyncMock, return_value=mock_redis),
        patch("app.core.redis.close_redis", new_callable=AsyncMock),
        patch("app.core.redis._client", mock_redis),
        patch(
            "app.services.market_data_client.market_data_client.aclose",
            new_callable=AsyncMock,
        ),
        patch(
            "app.consumers.candle_consumer.CandleConsumer.run",
            new_callable=AsyncMock,
        ),
        patch(
            "app.consumers.candle_consumer.CandleConsumer.shutdown",
            new_callable=AsyncMock,
        ),
        patch("app.main._retraining_loop", new_callable=AsyncMock),
        patch("app.main._drift_monitoring_loop", new_callable=AsyncMock),
    ]

    started = [p.start() for p in patches]

    async with AsyncClient(
        transport=ASGITransport(app=app.main.app),
        base_url="http://test",
    ) as c:
        yield c

    for p in patches:
        p.stop()
