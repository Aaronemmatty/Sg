"""Market breadth metrics (advance/decline) used to derive RISK_ON / RISK_OFF for the
market-wide (NIFTY50) regime, and as a divergence signal for per-symbol overrides."""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.domain import BreadthSnapshot, RegimeType


class BreadthCalculator:
    """
    Given the latest closing-price change (% return over one bar) for each symbol in a
    breadth universe, compute advance/decline counts and classify RISK_ON vs RISK_OFF.

    RISK_ON:  breadth strongly positive (most of the universe advancing)
    RISK_OFF: breadth strongly negative (most of the universe declining)
    Anything in between is breadth-neutral and does not contribute a breadth sub-regime.
    """

    def __init__(self, risk_on_threshold: float = 0.60, risk_off_threshold: float = 0.40):
        self.risk_on_threshold = risk_on_threshold
        self.risk_off_threshold = risk_off_threshold

    def compute(self, pct_changes: dict[str, float]) -> BreadthSnapshot:
        if not pct_changes:
            raise ValueError("pct_changes must contain at least one symbol")

        advancing = sum(1 for v in pct_changes.values() if v > 0.0)
        declining = sum(1 for v in pct_changes.values() if v < 0.0)
        unchanged = len(pct_changes) - advancing - declining
        universe_size = len(pct_changes)
        advance_pct = advancing / universe_size

        if advance_pct >= self.risk_on_threshold:
            regime = RegimeType.RISK_ON
        elif advance_pct <= self.risk_off_threshold:
            regime = RegimeType.RISK_OFF
        else:
            # Neutral breadth: lean on majority direction without an extreme label.
            regime = RegimeType.RISK_ON if advance_pct >= 0.5 else RegimeType.RISK_OFF

        return BreadthSnapshot(
            advancing=advancing,
            declining=declining,
            unchanged=unchanged,
            universe_size=universe_size,
            advance_pct=advance_pct,
            breadth_regime=regime,
            timestamp=datetime.now(timezone.utc),
        )

    def is_extreme(self, snapshot: BreadthSnapshot) -> bool:
        """Whether breadth is strong enough to count as a confident sub-regime signal."""
        return snapshot.advance_pct >= self.risk_on_threshold or snapshot.advance_pct <= self.risk_off_threshold
