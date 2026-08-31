"""Intent publisher — publishes TradeIntent to sg:intents:{symbol}."""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import INTENTS_PUBLISHED
from app.core.redis import get_redis
from app.models.domain import TradeIntent
from app.schemas.events import TradeIntentEvent

settings = get_settings()
log = get_logger(__name__)


class IntentPublisher:
    async def publish(self, intent: TradeIntent) -> None:
        try:
            redis = await get_redis()
            event = TradeIntentEvent.from_domain(intent)
            channel = f"{settings.REDIS_CHANNEL_INTENTS_PREFIX}:{intent.symbol}"
            payload = event.to_json()

            await redis.publish(channel, payload)

            INTENTS_PUBLISHED.labels(
                symbol=intent.symbol, action=intent.action.value
            ).inc()

            log.info(
                "intent_published",
                channel=channel,
                intent_id=intent.intent_id,
                symbol=intent.symbol,
                status=intent.status.value,
                action=intent.action.value,
                allocation_inr=intent.allocation_inr,
            )
        except Exception as exc:
            log.error(
                "intent_publish_failed",
                intent_id=intent.intent_id,
                symbol=intent.symbol,
                error=str(exc),
                exc_info=True,
            )
            raise
