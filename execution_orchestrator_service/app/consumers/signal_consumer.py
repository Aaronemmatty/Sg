"""
Redis pub/sub consumer — approved signals and regime updates.

Two subscriptions run in the same asyncio task:
  sg:approved:*  → feed into orchestration pipeline
  sg:regime:*    → update local regime cache
"""
from __future__ import annotations

import asyncio
import json

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import CONSUMER_ERRORS, CONSUMER_RECONNECTS
from app.core.redis import get_redis
from app.db.session import AsyncSessionLocal
from app.models.domain import TradeAction
from app.schemas.events import ApprovedSignalEvent, RegimeEvent
from app.services.orchestrator_service import OrchestratorService

settings = get_settings()
log = get_logger(__name__)

_RECONNECT_DELAY_S = 2.0
_MAX_RECONNECT_DELAY_S = 30.0


class SignalConsumer:
    """
    Subscribes to:
      - sg:approved:*   (pattern)
      - sg:regime:*     (pattern)

    Uses a single pubsub connection with pattern subscriptions.
    On disconnect, retries with exponential backoff (capped at 30s).
    """

    def __init__(
        self,
        orchestrator: OrchestratorService,
        regime_cache: dict[str, str],
    ) -> None:
        self._orchestrator = orchestrator
        self._regime_cache = regime_cache
        self._running = False
        self._task: asyncio.Task | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(
            self._run_with_backoff(), name="signal_consumer"
        )
        log.info("signal_consumer_started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("signal_consumer_stopped")

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def _run_with_backoff(self) -> None:
        delay = _RECONNECT_DELAY_S
        while self._running:
            try:
                await self._consume()
                delay = _RECONNECT_DELAY_S  # reset on clean exit
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error(
                    "signal_consumer_crashed",
                    error=str(exc),
                    retry_in_s=delay,
                    exc_info=True,
                )
                CONSUMER_RECONNECTS.labels(consumer="signal").inc()
                await asyncio.sleep(delay)
                delay = min(delay * 2, _MAX_RECONNECT_DELAY_S)

    async def _consume(self) -> None:
        redis = await get_redis()
        pubsub: aioredis.client.PubSub = redis.pubsub()

        approved_pattern = f"{settings.REDIS_CHANNEL_APPROVED_PREFIX}:*"
        regime_pattern = f"{settings.REDIS_CHANNEL_REGIME_PREFIX}:*"

        await pubsub.psubscribe(approved_pattern, regime_pattern)
        log.info(
            "signal_consumer_subscribed",
            approved_pattern=approved_pattern,
            regime_pattern=regime_pattern,
        )

        try:
            async for message in pubsub.listen():
                if not self._running:
                    break
                if message["type"] != "pmessage":
                    continue
                await self._dispatch(message)
        finally:
            await pubsub.punsubscribe()
            await pubsub.aclose()

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch(self, message: dict) -> None:
        channel: str = message.get("channel", "")
        data: str = message.get("data", "")

        try:
            if channel.startswith(settings.REDIS_CHANNEL_APPROVED_PREFIX):
                await self._handle_approved_signal(channel, data)
            elif channel.startswith(settings.REDIS_CHANNEL_REGIME_PREFIX):
                await self._handle_regime_update(channel, data)
        except Exception as exc:
            log.error(
                "consumer_dispatch_error",
                channel=channel,
                error=str(exc),
                exc_info=True,
            )
            CONSUMER_ERRORS.labels(consumer="signal").inc()

    async def _handle_approved_signal(self, channel: str, raw: str) -> None:
        try:
            event = ApprovedSignalEvent.from_redis_message(raw)
            signal = event.to_domain()
        except Exception as exc:
            log.warning(
                "approved_signal_parse_error",
                channel=channel,
                error=str(exc),
            )
            CONSUMER_ERRORS.labels(consumer="signal").inc()
            return

        if signal.final_signal == TradeAction.HOLD:
            log.debug("signal_is_hold_skipping", symbol=signal.symbol)
            return

        log.info(
            "approved_signal_received",
            symbol=signal.symbol,
            confidence=signal.confidence,
            action=signal.final_signal.value,
            timeframe=signal.timeframe,
        )

        async with AsyncSessionLocal() as db:
            try:
                await self._orchestrator.handle_signal(
                    signal=signal,
                    db=db,
                    portfolio_id=settings.DEFAULT_PORTFOLIO_ID or None,
                )
            except Exception as exc:
                log.error(
                    "orchestration_failed",
                    symbol=signal.symbol,
                    error=str(exc),
                    exc_info=True,
                )
                CONSUMER_ERRORS.labels(consumer="signal").inc()

    async def _handle_regime_update(self, channel: str, raw: str) -> None:
        try:
            event = RegimeEvent.from_redis_message(raw)
            self._regime_cache[event.symbol] = event.regime
            log.debug(
                "regime_cache_updated",
                symbol=event.symbol,
                regime=event.regime,
                confidence=event.confidence,
            )
        except Exception as exc:
            log.warning(
                "regime_event_parse_error",
                channel=channel,
                error=str(exc),
            )
