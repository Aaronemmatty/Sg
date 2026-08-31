"""
SignalAggregationEngine: the orchestrator. For a given (symbol, timeframe):
  1. Collect raw strategy signals (registry + SCAN-discovered) and the current regime.
  2. Normalize each raw signal into a SignalVote, dropping stale ones.
  3. Resolve effective weights for this regime over the strategies that actually voted
     (refreshing the DB-backed override cache first).
  4. Compute the ConflictReport (net score, agreement ratio) via ConfidenceEngine.
  5. Decide the final action via ConflictResolutionEngine and compute final confidence.
  6. Build the AggregatedSignalResult, persist a snapshot, cache it, and publish it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.conflict import ConflictResolutionEngine
from app.core.confidence import ConfidenceEngine
from app.core.normalization import normalize_signal_allow_stale
from app.core.weighting import WeightingEngine
from app.models.domain import AggregatedSignalResult, SignalVote
from app.services.redis_client import AggregationRedisClient
from app.services.weight_store import WeightStore

logger = logging.getLogger(__name__)


class NoSignalsAvailableError(Exception):
    pass


class SignalAggregationEngine:
    def __init__(
        self,
        settings: Settings,
        redis_client: AggregationRedisClient,
        weight_store: WeightStore,
    ):
        self.settings = settings
        self.redis = redis_client
        self.weight_store = weight_store
        self.weighting_engine = WeightingEngine(settings, override_provider=weight_store)
        self.confidence_engine = ConfidenceEngine(settings)
        self.conflict_engine = ConflictResolutionEngine(settings)

    async def aggregate(
        self, session: AsyncSession, symbol: str, timeframe: str | None = None
    ) -> AggregatedSignalResult:
        timeframe = timeframe or self.settings.DEFAULT_TIMEFRAME
        now = datetime.now(timezone.utc)

        raw_signals = await self.redis.collect_all_raw_signals(symbol, timeframe)
        if not raw_signals:
            raise NoSignalsAvailableError(f"no strategy signals available for {symbol}:{timeframe}")

        votes: list[SignalVote] = []
        stale_count = 0
        for strategy, raw in raw_signals.items():
            vote = normalize_signal_allow_stale(raw, self.settings, now=now)
            if vote is None:
                continue
            if vote.is_stale:
                stale_count += 1
                continue
            votes.append(vote)

        if not votes:
            raise NoSignalsAvailableError(
                f"all {len(raw_signals)} signal(s) for {symbol}:{timeframe} are stale or malformed"
            )

        regime_ref = await self.redis.get_regime(symbol, timeframe)
        regime = regime_ref.regime if regime_ref else "UNKNOWN"

        await self.weight_store.refresh(session, regime)
        weight_set = self.weighting_engine.resolve(regime, [v.strategy for v in votes])

        report = self.confidence_engine.compute(votes, weight_set)
        final_signal = self.conflict_engine.decide(report)
        confidence = self.confidence_engine.final_confidence(report)
        contributors = self.conflict_engine.contributors(votes, final_signal)

        votes_detail = {
            v.strategy: {
                "action": v.raw_action.value,
                "confidence": v.confidence,
                "weight": round(weight_set.effective_weights.get(v.strategy, 0.0), 4),
            }
            for v in votes
        }

        result = AggregatedSignalResult(
            symbol=symbol,
            timeframe=timeframe,
            final_signal=final_signal,
            confidence=confidence,
            contributors=contributors,
            regime=regime,
            net_score=report.net_score,
            agreement_ratio=report.agreement_ratio,
            votes=votes_detail,
            timestamp=now,
            weights_version="static_v1+db_overrides",
        )

        if stale_count:
            logger.info(
                "aggregated %s:%s — ignored %d stale signal(s)", symbol, timeframe, stale_count
            )

        await self._persist_and_publish(session, result)
        return result

    async def _persist_and_publish(self, session: AsyncSession, result: AggregatedSignalResult) -> None:
        await self.redis.set_cached_result(result)
        await self._save_snapshot(session, result)
        await self.redis.publish_result(result)
        logger.info(
            "AGGREGATED %s:%s -> %s (confidence=%.2f, contributors=%s, regime=%s)",
            result.symbol, result.timeframe, result.final_signal.value,
            result.confidence, result.contributors, result.regime,
        )

    async def _save_snapshot(self, session: AsyncSession, result: AggregatedSignalResult) -> None:
        from app.models.db import AggregatedSignal

        snapshot = AggregatedSignal(
            tenant_id=self.settings.DEFAULT_TENANT_ID,
            symbol=result.symbol,
            timeframe=result.timeframe,
            timestamp=result.timestamp,
            final_signal=result.final_signal.value,
            confidence=result.confidence,
            contributors=result.contributors,
            regime=result.regime,
            net_score=result.net_score,
            agreement_ratio=result.agreement_ratio,
            votes=result.votes,
            weights_version=result.weights_version,
        )
        session.add(snapshot)
        await session.flush()
