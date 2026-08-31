"""
ML Signal Strategy — runs inference against a pre-trained sklearn model.

The model is loaded from the path in params["model_path"].
Features: [rsi_14, ema_9, ema_21, atr_14, volume_zscore, close_return_1, close_return_5]
Output: class probabilities [BUY, HOLD, SELL]
"""
from __future__ import annotations

import os
from typing import Optional

from app.sdk import (
    Signal, SignalType, StrategyBase, StrategyContext,
    StrategyMetadata, StrategyType,
)


class MLSignalStrategy(StrategyBase):
    METADATA = StrategyMetadata(
        name="ml_signal",
        version="1.0.0",
        strategy_type=StrategyType.ML,
        author="SG Platform",
        description="ML inference strategy using a pre-trained sklearn classifier.",
        timeframes=["5m", "15m"],
        symbols=["*"],
        min_bars_required=30,
        parameters={
            "model_path":       "/app/models/ml_signal_model.pkl",
            "min_confidence":   0.60,
            "feature_window":   14,
        },
        tags=["ml", "classification", "sklearn"],
    )

    def __init__(self) -> None:
        super().__init__()
        self._model = None

    async def on_start(self, params: dict) -> None:
        model_path = params.get("model_path", self.METADATA.parameters["model_path"])
        if os.path.exists(model_path):
            try:
                import joblib
                self._model = joblib.load(model_path)
            except Exception as exc:
                raise RuntimeError(f"Failed to load ML model from {model_path}: {exc}")

    async def on_bar(self, ctx: StrategyContext) -> Optional[Signal]:
        if not self._has_enough_bars(ctx):
            return None
        if self._model is None:
            return None

        min_conf = self._param(ctx, "min_confidence", 0.60)
        features = self._extract_features(ctx)
        if features is None:
            return None

        try:
            import numpy as np
            probs = self._model.predict_proba([features])[0]
            classes = self._model.classes_
            class_map = {c: p for c, p in zip(classes, probs)}

            buy_prob  = class_map.get("BUY",  class_map.get(1, 0.0))
            sell_prob = class_map.get("SELL", class_map.get(-1, 0.0))
            hold_prob = class_map.get("HOLD", class_map.get(0, 0.0))

            if buy_prob >= min_conf and buy_prob == max(buy_prob, sell_prob, hold_prob):
                return self._make_signal(
                    SignalType.BUY, float(buy_prob), ctx,
                    metadata={"buy_prob": round(buy_prob, 4),
                              "sell_prob": round(sell_prob, 4)},
                )
            if sell_prob >= min_conf and sell_prob == max(buy_prob, sell_prob, hold_prob):
                return self._make_signal(
                    SignalType.SELL, float(sell_prob), ctx,
                    metadata={"buy_prob": round(buy_prob, 4),
                              "sell_prob": round(sell_prob, 4)},
                )
        except Exception:
            pass

        return None

    def _extract_features(self, ctx: StrategyContext) -> Optional[list]:
        closes  = ctx.close_prices
        volumes = ctx.volumes
        if len(closes) < 22:
            return None

        rsi   = _rsi(closes, 14) or 50.0
        ema9  = _ema(closes, 9)  or closes[-1]
        ema21 = _ema(closes, 21) or closes[-1]
        atr   = _atr_simple(ctx.bars[-15:], 14) or 1.0

        vol_mean = sum(volumes[-14:]) / 14
        vol_std  = max((_std(volumes[-14:])), 1)
        vol_z    = (volumes[-1] - vol_mean) / vol_std

        ret1 = (closes[-1] - closes[-2]) / closes[-2] if closes[-2] else 0.0
        ret5 = (closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 and closes[-6] else 0.0

        return [rsi, ema9, ema21, atr, vol_z, ret1, ret5]


def _rsi(closes, period):
    if len(closes) < period + 1:
        return None
    gains = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    return 100 - (100 / (1 + ag / al)) if al else 100.0

def _ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    e = sum(closes[:period]) / period
    for c in closes[period:]:
        e = c * k + e * (1 - k)
    return e

def _atr_simple(bars, period):
    if len(bars) < 2:
        return 0.0
    trs = [max(bars[i].high - bars[i].low,
               abs(bars[i].high - bars[i-1].close),
               abs(bars[i].low  - bars[i-1].close))
           for i in range(1, len(bars))]
    return sum(trs[-period:]) / min(period, len(trs))

def _std(values):
    import statistics
    return statistics.stdev(values) if len(values) > 1 else 0.0
