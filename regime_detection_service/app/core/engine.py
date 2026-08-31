"""
RegimeDetectionEngine: the orchestrator that ties feature engineering, the hybrid
classifier, market breadth, and transition detection together into a single
`detect()` call per symbol/timeframe.

Scope behavior (per locked decision):
  - The market-wide regime (PRIMARY_SYMBOL, e.g. NIFTY50) is always computed and is the
    primary signal strategies should key off.
  - A per-symbol regime is computed independently, but it is only reported/cached/published
    as an *override* when it diverges materially from the market-wide regime (divergence
    score >= PER_SYMBOL_DIVERGENCE_THRESHOLD). Otherwise the per-symbol result simply
    confirms/inherits the market regime, marked `is_override=False`.
"""
from __future__ import annotations

import logging
from datetime import timezone

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.breadth import BreadthCalculator
from app.core.classifier import HybridClassifier
from app.core.features import compute_feature_set
from app.core.transitions import TransitionDetector
from app.models.domain import BreadthSnapshot, RegimeResult, RegimeTransition
from app.services import market_data_client
from app.services.redis_client import RegimeRedisClient

logger = logging.getLogger(__name__)


class InsufficientDataError(Exception):
    pass


class RegimeDetectionEngine:
    def __init__(self, settings: Settings, redis_client: RegimeRedisClient, classifier: HybridClassifier):
        self.settings = settings
        self.redis = redis_client
        self.classifier = classifier
        self.breadth_calc = BreadthCalculator()
        self.transition_detector = TransitionDetector(
            confirm_bars=settings.TRANSITION_CONFIRM_BARS,
            min_confidence=settings.MIN_CONFIDENCE_FOR_TRANSITION,
        )

    # --- Public API ---------------------------------------------------------------

    async def detect_market_wide(self, session: AsyncSession, timeframe: str | None = None) -> RegimeResult:
        """Compute the primary, market-wide regime (NIFTY50 proxy)."""
        timeframe = timeframe or self.settings.DEFAULT_TIMEFRAME
        symbol = self.settings.PRIMARY_SYMBOL

        breadth = await self._compute_breadth(session, timeframe)
        result = await self._detect_single(session, symbol, timeframe, breadth=breadth, is_override=False)
        return result

    async def detect_symbol(
        self, session: AsyncSession, symbol: str, timeframe: str | None = None
    ) -> RegimeResult:
        """
        Compute the per-symbol regime and decide whether it overrides the market-wide
        regime (only when divergence is material), per the locked scope decision.
        """
        timeframe = timeframe or self.settings.DEFAULT_TIMEFRAME

        market_result = await self.redis.get_cached_regime(self.settings.PRIMARY_SYMBOL, timeframe)
        if market_result is None:
            market_result = await self.detect_market_wide(session, timeframe)
            await self.persist_and_publish(session, market_result)

        symbol_result = await self._detect_single(session, symbol, timeframe, breadth=None, is_override=False)

        divergence = self._divergence_score(market_result, symbol_result)
        if divergence >= self.settings.PER_SYMBOL_DIVERGENCE_THRESHOLD:
            symbol_result.is_override = True
            logger.info(
                "symbol %s diverges from market regime (score=%.2f) — reporting override %s",
                symbol, divergence, symbol_result.regime,
            )
        else:
            # Inherit the market structure regime but keep the symbol's own confidence/features
            # for transparency; this keeps strategies that key off `regime` aligned with the
            # index unless there's a real reason not to be.
            symbol_result.regime = market_result.regime
            symbol_result.is_override = False

        await self.persist_and_publish(session, symbol_result)
        return symbol_result

    async def detect(
        self, session: AsyncSession, symbol: str, timeframe: str | None = None
    ) -> RegimeResult:
        """Convenience dispatcher: market-wide symbol vs per-symbol path."""
        timeframe = timeframe or self.settings.DEFAULT_TIMEFRAME
        if symbol == self.settings.PRIMARY_SYMBOL:
            result = await self.detect_market_wide(session, timeframe)
            await self.persist_and_publish(session, result)
            return result
        return await self.detect_symbol(session, symbol, timeframe)

    # --- Internal helpers -----------------------------------------------------------

    async def _detect_single(
        self,
        session: AsyncSession,
        symbol: str,
        timeframe: str,
        breadth: BreadthSnapshot | None,
        is_override: bool,
    ) -> RegimeResult:
        df = await market_data_client.get_recent_bars(
            session,
            self.settings,
            symbol,
            timeframe,
            limit=max(200, self.settings.MIN_BARS_REQUIRED * 3),
        )
        if df.empty or len(df) < self.settings.MIN_BARS_REQUIRED:
            raise InsufficientDataError(
                f"not enough bars for {symbol}:{timeframe} "
                f"(have {len(df)}, need {self.settings.MIN_BARS_REQUIRED})"
            )

        vix_value = await self._get_vix(session)
        breadth_pct = breadth.advance_pct if breadth else None

        features = compute_feature_set(df, self.settings, vix_value=vix_value, breadth_pct=breadth_pct)
        classification = self.classifier.classify(features, breadth=breadth)

        latest_ts = df["timestamp"].iloc[-1]
        if isinstance(latest_ts, pd.Timestamp):
            latest_ts = latest_ts.to_pydatetime()
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)

        return RegimeResult(
            regime=classification.regime,
            confidence=classification.confidence,
            sub_regimes=classification.sub_regimes,
            symbol=symbol,
            timeframe=timeframe,
            timestamp=latest_ts,
            features=features.as_dict(),
            model_version=classification.model_version,
            is_override=is_override,
        )

    async def _compute_breadth(self, session: AsyncSession, timeframe: str) -> BreadthSnapshot:
        pct_changes: dict[str, float] = {}
        for sym in self.settings.BREADTH_UNIVERSE_SYMBOLS:
            try:
                df = await market_data_client.get_recent_bars(
                    session, self.settings, sym, timeframe, limit=2
                )
                if len(df) >= 2:
                    prev_close = df["close"].iloc[-2]
                    last_close = df["close"].iloc[-1]
                    pct_changes[sym] = (last_close - prev_close) / prev_close if prev_close else 0.0
            except Exception:  # noqa: BLE001
                logger.warning("breadth: skipping %s due to data error", sym, exc_info=True)
        if not pct_changes:
            # Degenerate but non-fatal: treat as neutral breadth.
            pct_changes = {"_none": 0.0}
        return self.breadth_calc.compute(pct_changes)

    async def _get_vix(self, session: AsyncSession) -> float | None:
        cached = await self.redis.get_latest_tick(self.settings.PRIMARY_EXCHANGE, self.settings.VIX_SYMBOL)
        if cached and "last_price" in cached:
            return float(cached["last_price"])
        return None

    @staticmethod
    def _divergence_score(market: RegimeResult, symbol: RegimeResult) -> float:
        """
        0-1 divergence score between the market-wide and a symbol's standalone read.
        Combines: structure mismatch, direction mismatch, and feature-level distance on
        trend_slope/atr_pct (normalized), keeping this cheap and explainable rather than
        a learned similarity metric.
        """
        score = 0.0
        if market.regime != symbol.regime:
            score += 0.5

        market_dir = market.features.get("trend_slope", 0.0)
        symbol_dir = symbol.features.get("trend_slope", 0.0)
        if (market_dir >= 0) != (symbol_dir >= 0):
            score += 0.3

        market_vol = market.features.get("atr_pct", 0.0)
        symbol_vol = symbol.features.get("atr_pct", 0.0)
        vol_gap = abs(market_vol - symbol_vol)
        score += min(0.2, vol_gap * 10)  # small contribution, capped

        return min(1.0, score)

    async def persist_and_publish(self, session: AsyncSession, result: RegimeResult) -> None:
        previous = await self.redis.get_cached_regime(result.symbol, result.timeframe)

        await self.redis.set_cached_regime(result)
        await self._save_snapshot(session, result)
        await self.redis.publish_regime_event(result, event_type="regime_update")

        transition = self.transition_detector.evaluate(previous, result)
        if transition is not None:
            await self._save_transition(session, transition)
            await self.redis.publish_regime_event(result, event_type="regime_change")
            logger.info(
                "CONFIRMED regime transition %s: %s -> %s (confidence=%.2f, reason=%s)",
                result.symbol, transition.from_regime, transition.to_regime,
                transition.confidence, transition.trigger_reason,
            )

    async def _save_snapshot(self, session: AsyncSession, result: RegimeResult) -> None:
        from app.models.db import RegimeSnapshot

        snapshot = RegimeSnapshot(
            tenant_id=self.settings.DEFAULT_TENANT_ID,
            symbol=result.symbol,
            exchange=self.settings.PRIMARY_EXCHANGE,
            timeframe=result.timeframe,
            timestamp=result.timestamp,
            regime=result.regime.value,
            confidence=result.confidence,
            sub_regimes=[r.value for r in result.sub_regimes],
            features=result.features,
            model_version=result.model_version,
            is_override=result.is_override,
        )
        session.add(snapshot)
        await session.flush()

    async def _save_transition(self, session: AsyncSession, transition: RegimeTransition) -> None:
        from app.models.db import RegimeTransitionRecord

        record = RegimeTransitionRecord(
            tenant_id=self.settings.DEFAULT_TENANT_ID,
            symbol=transition.symbol,
            timeframe=transition.timeframe,
            timestamp=transition.timestamp,
            from_regime=transition.from_regime.value if transition.from_regime else None,
            to_regime=transition.to_regime.value,
            confidence=transition.confidence,
            trigger_reason=transition.trigger_reason,
        )
        session.add(record)
        await session.flush()
