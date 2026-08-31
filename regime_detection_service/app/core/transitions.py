"""
Regime change detection with debouncing.

Naively flipping a "current regime" label every time the classifier wobbles near a
threshold creates noisy, useless alerts. This module requires a candidate new regime to
be confirmed over `confirm_bars` consecutive recalculations (and to clear a minimum
confidence bar) before it is treated as a genuine transition that gets persisted and
published.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.domain import RegimeResult, RegimeTransition, RegimeType


class TransitionDetector:
    def __init__(self, confirm_bars: int = 2, min_confidence: float = 0.55):
        self.confirm_bars = max(1, confirm_bars)
        self.min_confidence = min_confidence
        # per (symbol, timeframe) -> (candidate_regime, consecutive_count)
        self._pending: dict[tuple[str, str], tuple[RegimeType, int]] = {}

    def evaluate(
        self,
        previous: RegimeResult | None,
        candidate: RegimeResult,
    ) -> RegimeTransition | None:
        """
        Returns a confirmed RegimeTransition if `candidate` represents a debounced,
        confident change from `previous`. Returns None otherwise (including the very
        first observation, where there is nothing to transition from).
        """
        key = (candidate.symbol, candidate.timeframe)

        if previous is None:
            # First-ever observation for this symbol/timeframe: nothing to transition
            # from, but seed the debounce state so subsequent calls behave correctly.
            self._pending[key] = (candidate.regime, 1)
            return None

        if candidate.regime == previous.regime:
            # No change candidate; reset any pending flip.
            self._pending.pop(key, None)
            return None

        if candidate.confidence < self.min_confidence:
            # Low-confidence flip candidates don't even start the debounce clock.
            self._pending.pop(key, None)
            return None

        last_candidate, count = self._pending.get(key, (candidate.regime, 0))
        if last_candidate == candidate.regime:
            count += 1
        else:
            count = 1
        self._pending[key] = (candidate.regime, count)

        if count < self.confirm_bars:
            return None

        # Confirmed transition.
        self._pending.pop(key, None)
        return RegimeTransition(
            symbol=candidate.symbol,
            timeframe=candidate.timeframe,
            from_regime=previous.regime,
            to_regime=candidate.regime,
            confidence=candidate.confidence,
            timestamp=candidate.timestamp or datetime.now(timezone.utc),
            trigger_reason=self._infer_reason(previous, candidate),
        )

    @staticmethod
    def _infer_reason(previous: RegimeResult, candidate: RegimeResult) -> str:
        vol_regimes = {RegimeType.HIGH_VOLATILITY, RegimeType.LOW_VOLATILITY}
        if candidate.regime in vol_regimes or previous.regime in vol_regimes:
            return "volatility_shift"
        breadth_regimes = {RegimeType.RISK_ON, RegimeType.RISK_OFF}
        if candidate.regime in breadth_regimes or previous.regime in breadth_regimes:
            return "breadth_shift"
        return "structure_flip"
