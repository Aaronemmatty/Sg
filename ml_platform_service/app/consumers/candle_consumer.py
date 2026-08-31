"""
Candle Consumer.

Subscribes to sg:market:candle:* (same channel published by market_data_service / 8002).
On each new candle:
  1. Fetch recent OHLCV history from market_data_service REST API
  2. Compute FeatureVector via FeatureEngineer
  3. Cache feature in Redis + persist snapshot to DB
  4. Run ensemble prediction
  5. Publish MLSignal if confidence ≥ threshold
  6. Publish MLRegimeUpdate to sg:ml:regime:{symbol}
"""
from __future__ import annotations

import asyncio
import json

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger
from app.features.engineer import FeatureEngineer
from app.features.store import cache_feature_vector, persist_feature_snapshot
from app.models.domain import MLRegimeUpdate, ModelType
from app.serving.predictor import predict_ensemble, publish_signal

log = get_logger(__name__)
_engineer = FeatureEngineer()


class CandleConsumer:
    """
    Pattern-subscribes to sg:market:candle:* and drives the real-time
    feature + prediction pipeline on each incoming bar.
    """

    def __init__(self, redis_client: redis.Redis, md_client) -> None:
        self._redis = redis_client
        self._md_client = md_client
        self._pubsub: redis.client.PubSub | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(settings.redis_candle_pattern)
        log.info("candle_consumer_started", pattern=settings.redis_candle_pattern)

        async for message in self._pubsub.listen():
            if stop_event.is_set():
                break
            if message["type"] != "pmessage":
                continue
            try:
                payload = json.loads(message["data"])
                symbol = payload.get("symbol", "").upper()
                if not symbol:
                    continue
                # Fire-and-forget per symbol — don't block the consumer loop
                asyncio.create_task(self._process(symbol, payload))
            except Exception:
                log.exception("candle_consumer_parse_error")

        log.info("candle_consumer_stopped")

    async def _process(self, symbol: str, candle: dict) -> None:
        try:
            # 1. Fetch OHLCV history for feature computation
            df = await self._md_client.get_ohlcv(symbol, bars=settings.feature_lookback_bars)
            if df is None or len(df) < 50:
                log.debug("insufficient_ohlcv_for_features", symbol=symbol)
                return

            # 2. Compute features
            fv = _engineer.compute_latest(df, symbol)

            # 3. Cache + persist
            await cache_feature_vector(fv)
            await persist_feature_snapshot(fv)

            # 4. Ensemble predict
            batch = _engineer.compute_batch(df, symbol)
            ensemble = await predict_ensemble(symbol, fv, feature_batch=batch)
            if ensemble is None:
                return

            # 5. Publish ML signal
            await publish_signal(ensemble)

            # 6. Publish regime update
            await self._publish_regime_update(symbol, ensemble)

        except Exception:
            log.exception("candle_consumer_process_error", symbol=symbol)

    async def _publish_regime_update(self, symbol: str, ensemble) -> None:
        """Derive regime probabilities from ensemble and publish to sg:ml:regime:{symbol}."""
        try:
            long_votes = sum(
                p.raw_probabilities.get("up", 0) for p in ensemble.model_predictions
            )
            short_votes = sum(
                p.raw_probabilities.get("down", 0) for p in ensemble.model_predictions
            )
            n = max(len(ensemble.model_predictions), 1)

            update = MLRegimeUpdate(
                symbol=symbol,
                bull_probability=long_votes / n,
                bear_probability=short_votes / n,
                neutral_probability=max(0.0, 1.0 - (long_votes + short_votes) / n),
                predicted_vol_regime=(
                    "high" if ensemble.ensemble_confidence < 0.6
                    else "medium" if ensemble.ensemble_confidence < 0.75
                    else "low"
                ),
            )
            channel = f"{settings.redis_ml_regime_prefix}:{symbol}"
            await self._redis.publish(channel, update.model_dump_json())
        except Exception:
            log.warning("regime_update_publish_failed", symbol=symbol)

    async def shutdown(self) -> None:
        if self._pubsub:
            await self._pubsub.close()
