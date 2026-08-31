"""Signal publisher — Redis pub/sub + PostgreSQL write."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.sdk.types import Signal

settings = get_settings()
log = get_logger(__name__)


class SignalPublisher:
    async def publish(self, signal: Signal) -> None:
        await self._publish_redis(signal)
        await self._persist_postgres(signal)

    async def _publish_redis(self, signal: Signal) -> None:
        try:
            r = await get_redis()
            channel = f"{settings.REDIS_SIGNAL_CHANNEL_PREFIX}:{signal.symbol}"
            payload = json.dumps(signal.to_dict())
            await r.publish(channel, payload)
            # Cache latest signal per strategy+symbol
            cache_key = f"signal:{signal.strategy_name}:{signal.symbol}:{signal.timeframe}"
            await r.setex(cache_key, settings.SIGNAL_EXPIRY_S, payload)
        except Exception as exc:
            log.error("signal_redis_publish_failed",
                      symbol=signal.symbol, strategy=signal.strategy_name, error=str(exc))

    async def _persist_postgres(self, signal: Signal) -> None:
        try:
            from app.db.session import AsyncSessionLocal
            from sg_db.models.signals import Signal as SignalModel
            async with AsyncSessionLocal() as session:
                record = SignalModel(
                    strategy_name=signal.strategy_name,
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    signal_type=signal.signal.value,
                    confidence=signal.confidence,
                    entry_price=signal.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    suggested_quantity=signal.suggested_quantity,
                    metadata_=signal.metadata,
                    emitted_at=signal.timestamp,
                )
                session.add(record)
                await session.commit()
        except Exception as exc:
            log.error("signal_postgres_persist_failed",
                      symbol=signal.symbol, strategy=signal.strategy_name, error=str(exc))
