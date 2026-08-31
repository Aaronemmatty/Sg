from __future__ import annotations

import pytest

from app.core.weighting import WeightingEngine


def test_resolve_uses_static_defaults_when_all_strategies_report(settings):
    engine = WeightingEngine(settings)
    result = engine.resolve("TRENDING", ["trend_following", "breakout", "momentum", "ml_prediction"])
    assert result.effective_weights["trend_following"] == pytest.approx(0.40)
    assert result.effective_weights["breakout"] == pytest.approx(0.30)
    assert sum(result.effective_weights.values()) == pytest.approx(1.0)
    assert result.unmapped_strategies == []


def test_resolve_renormalizes_when_a_strategy_is_missing(settings):
    """ML didn't report this cycle — its 10% weight should be redistributed, not dropped."""
    engine = WeightingEngine(settings)
    result = engine.resolve("TRENDING", ["trend_following", "breakout", "momentum"])
    assert sum(result.effective_weights.values()) == pytest.approx(1.0)
    # Relative ordering preserved: trend > breakout > momentum
    assert (
        result.effective_weights["trend_following"]
        > result.effective_weights["breakout"]
        > result.effective_weights["momentum"]
    )
    # trend_following's share should now exceed its raw 0.40 since ML's weight was redistributed
    assert result.effective_weights["trend_following"] > 0.40


def test_resolve_handles_unmapped_custom_strategy(settings):
    engine = WeightingEngine(settings)
    result = engine.resolve("TRENDING", ["trend_following", "my_custom_strategy"])
    assert "my_custom_strategy" in result.unmapped_strategies
    assert result.raw_weights["my_custom_strategy"] == settings.DEFAULT_UNMAPPED_STRATEGY_WEIGHT
    assert sum(result.effective_weights.values()) == pytest.approx(1.0)


def test_resolve_falls_back_to_fallback_weights_for_unknown_regime(settings):
    engine = WeightingEngine(settings)
    result = engine.resolve("SOME_UNDEFINED_REGIME", ["trend_following", "mean_reversion"])
    assert sum(result.effective_weights.values()) == pytest.approx(1.0)
    assert result.unmapped_strategies == []  # both are in FALLBACK_WEIGHTS


def test_resolve_db_override_takes_precedence_over_static_default(settings):
    class FakeOverrideProvider:
        def get_overrides(self, regime):
            return {"trend_following": 0.99}

    engine = WeightingEngine(settings, override_provider=FakeOverrideProvider())
    result = engine.resolve("TRENDING", ["trend_following", "breakout"])
    # trend_following's raw weight should reflect the override (0.99), not the static 0.40
    assert result.raw_weights["trend_following"] == pytest.approx(0.99)


def test_resolve_handles_degenerate_all_zero_weights(settings):
    settings.DEFAULT_UNMAPPED_STRATEGY_WEIGHT = 0.0
    engine = WeightingEngine(settings)
    result = engine.resolve("TRENDING", ["totally_unknown_a", "totally_unknown_b"])
    # All-zero raw weights -> even split fallback, never a ZeroDivisionError
    assert sum(result.effective_weights.values()) == pytest.approx(1.0)
    assert result.effective_weights["totally_unknown_a"] == pytest.approx(0.5)
