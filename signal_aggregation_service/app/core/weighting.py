"""
WeightingEngine: resolves the effective weight for each voting strategy given the current
regime, by layering DB-backed overrides on top of the static DEFAULT_REGIME_WEIGHTS, then
renormalizing over only the strategies that actually have a (non-stale) vote this run.

Renormalization matters: if the configured TRENDING weights are
trend=0.40/breakout=0.30/momentum=0.20/ml=0.10 but ML didn't report this cycle, naively
using the raw weights would silently throw away 10% of the vote. Renormalizing over the
three that *did* report keeps the relative weighting intact and the total at 1.0.
"""
from __future__ import annotations

from app.config import DEFAULT_REGIME_WEIGHTS, FALLBACK_WEIGHTS, Settings
from app.models.domain import WeightSet


class WeightingEngine:
    def __init__(self, settings: Settings, override_provider=None):
        """
        `override_provider`: optional callable/object exposing
        `get_overrides(regime: str) -> dict[str, float]` (DB-backed). If None, only the
        static defaults are used — handy for unit tests and for environments without a
        DB connection.
        """
        self.settings = settings
        self.override_provider = override_provider

    def _configured_weights(self, regime: str) -> dict[str, float]:
        base = dict(DEFAULT_REGIME_WEIGHTS.get(regime, FALLBACK_WEIGHTS))
        if self.override_provider is not None:
            overrides = self.override_provider.get_overrides(regime) or {}
            base.update(overrides)  # DB overrides win over static defaults, per-strategy
        return base

    def resolve(self, regime: str, voting_strategies: list[str]) -> WeightSet:
        configured = self._configured_weights(regime)

        raw_weights: dict[str, float] = {}
        unmapped: list[str] = []
        for strategy in voting_strategies:
            if strategy in configured:
                raw_weights[strategy] = configured[strategy]
            else:
                raw_weights[strategy] = self.settings.DEFAULT_UNMAPPED_STRATEGY_WEIGHT
                unmapped.append(strategy)

        total = sum(raw_weights.values())
        if total <= 0:
            # Degenerate case (e.g. everyone unmapped with a zero fallback weight):
            # split evenly rather than divide by zero.
            n = max(1, len(raw_weights))
            effective = {s: 1.0 / n for s in raw_weights}
        else:
            effective = {s: w / total for s, w in raw_weights.items()}

        return WeightSet(
            regime=regime,
            raw_weights=raw_weights,
            effective_weights=effective,
            unmapped_strategies=unmapped,
        )
