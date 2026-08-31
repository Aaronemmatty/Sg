"""
Historical regime backtesting: replays the classifier over a historical OHLCV window,
bar by bar, producing the same RegimeResult contract a live recalculation would, plus the
transition log that would have fired. Strategy backtests (strategy_service) can use this
to evaluate how a strategy would have behaved conditioned on regime.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.classifier import HybridClassifier
from app.core.features import compute_feature_set
from app.core.transitions import TransitionDetector
from app.models.domain import (
    BacktestResponse,
    BacktestResultPoint,
    RegimeResult,
)
from app.services import market_data_client


async def run_backtest(
    session: AsyncSession,
    settings: Settings,
    classifier: HybridClassifier,
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> BacktestResponse:
    df = await market_data_client.fetch_range_bars_via_db(
        session, symbol, settings.PRIMARY_EXCHANGE, timeframe, start, end
    )
    if df.empty or len(df) < settings.MIN_BARS_REQUIRED:
        return BacktestResponse(symbol=symbol, timeframe=timeframe, points=[], transitions=[])

    df = df.sort_values("timestamp").reset_index(drop=True)
    detector = TransitionDetector(
        confirm_bars=settings.TRANSITION_CONFIRM_BARS,
        min_confidence=settings.MIN_CONFIDENCE_FOR_TRANSITION,
    )

    points: list[BacktestResultPoint] = []
    transitions = []
    previous_result: RegimeResult | None = None

    min_bars = settings.MIN_BARS_REQUIRED
    # NOTE: recomputing the full feature set on a growing window each iteration is simple
    # and correct but O(n^2) in bar count. For long backtests (multi-year, intraday),
    # swap to `app.core.features.compute_feature_frame` (fully vectorized) and iterate the
    # resulting feature rows instead — left as the straightforward path here since 5m bars
    # over a few years (~1e5 rows) still completes in low single-digit seconds.
    for i in range(min_bars, len(df) + 1):
        window = df.iloc[:i]
        features = compute_feature_set(window, settings)
        classification = classifier.classify(features)

        ts = window["timestamp"].iloc[-1]
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        result = RegimeResult(
            regime=classification.regime,
            confidence=classification.confidence,
            sub_regimes=classification.sub_regimes,
            symbol=symbol,
            timeframe=timeframe,
            timestamp=ts,
            features=features.as_dict(),
            model_version=classification.model_version,
        )
        points.append(
            BacktestResultPoint(
                timestamp=result.timestamp,
                regime=result.regime,
                confidence=result.confidence,
                sub_regimes=result.sub_regimes,
            )
        )

        transition = detector.evaluate(previous_result, result)
        if transition is not None:
            transitions.append(transition)
        previous_result = result

    return BacktestResponse(symbol=symbol, timeframe=timeframe, points=points, transitions=transitions)
