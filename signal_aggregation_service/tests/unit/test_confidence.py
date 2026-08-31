from __future__ import annotations

import pytest

from app.core.confidence import ConfidenceEngine
from app.core.weighting import WeightingEngine
from app.models.domain import SignalVote


def _vote(strategy: str, direction: int, confidence: float) -> SignalVote:
    from app.models.domain import SignalAction

    raw_action = {1: SignalAction.BUY, -1: SignalAction.SELL, 0: SignalAction.HOLD}[direction]
    return SignalVote(strategy=strategy, direction=direction, confidence=confidence, raw_action=raw_action)


def test_worked_example_from_brief(settings):
    """
    Trend BUY 0.80, Mean Reversion SELL 0.55, ML BUY 0.90, Breakout BUY 0.75, regime=TRENDING.
    Weights: trend=0.40, breakout=0.30, momentum=0.20 (no vote), ml=0.10.
    """
    votes = [
        _vote("trend_following", 1, 0.80),
        _vote("mean_reversion", -1, 0.55),
        _vote("ml_prediction", 1, 0.90),
        _vote("breakout", 1, 0.75),
    ]
    weighting = WeightingEngine(settings)
    weight_set = weighting.resolve("TRENDING", [v.strategy for v in votes])

    confidence_engine = ConfidenceEngine(settings)
    report = confidence_engine.compute(votes, weight_set)

    # Net score should be strongly positive (BUY) since trend+breakout+ml are all BUY and
    # outweigh mean_reversion's SELL, which isn't even in the TRENDING weight map.
    assert report.net_score > 0
    assert report.buy_weight > report.sell_weight

    final_confidence = confidence_engine.final_confidence(report)
    assert 0.0 < final_confidence <= 1.0


def test_unanimous_agreement_yields_high_confidence(settings):
    votes = [_vote("trend_following", 1, 0.9), _vote("breakout", 1, 0.9), _vote("momentum", 1, 0.9)]
    weighting = WeightingEngine(settings)
    weight_set = weighting.resolve("TRENDING", [v.strategy for v in votes])
    engine = ConfidenceEngine(settings)
    report = engine.compute(votes, weight_set)
    assert report.agreement_ratio == pytest.approx(1.0)
    assert engine.final_confidence(report) > 0.7


def test_even_split_dampens_confidence(settings):
    votes = [_vote("trend_following", 1, 0.9), _vote("mean_reversion", -1, 0.9)]
    weighting = WeightingEngine(settings)
    weight_set = weighting.resolve("RANGING", [v.strategy for v in votes])
    engine = ConfidenceEngine(settings)
    report = engine.compute(votes, weight_set)
    confidence = engine.final_confidence(report)
    # Even with strong individual confidences, a near-even directional split should not
    # produce a near-maximal final confidence.
    assert confidence < 0.9


def test_all_hold_yields_zero_agreement_and_low_confidence(settings):
    votes = [_vote("trend_following", 0, 0.5), _vote("breakout", 0, 0.5)]
    weighting = WeightingEngine(settings)
    weight_set = weighting.resolve("TRENDING", [v.strategy for v in votes])
    engine = ConfidenceEngine(settings)
    report = engine.compute(votes, weight_set)
    assert report.agreement_ratio == 0.0
    assert report.net_score == pytest.approx(0.0)
    assert engine.final_confidence(report) == 0.0


def test_thin_consensus_below_min_strategies_is_penalized(settings):
    settings.MIN_STRATEGIES_REQUIRED = 3
    votes = [_vote("trend_following", 1, 0.95)]
    weighting = WeightingEngine(settings)
    weight_set = weighting.resolve("TRENDING", [v.strategy for v in votes])
    engine = ConfidenceEngine(settings)
    report = engine.compute(votes, weight_set)
    penalized_confidence = engine.final_confidence(report)

    settings.MIN_STRATEGIES_REQUIRED = 1  # disable the penalty for comparison
    unpenalized_confidence = engine.final_confidence(report)
    assert penalized_confidence < unpenalized_confidence
