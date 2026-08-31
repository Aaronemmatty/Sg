from __future__ import annotations

from app.core.conflict import ConflictResolutionEngine
from app.models.domain import ConflictReport, SignalAction, SignalVote


def _vote(strategy: str, direction: int, confidence: float) -> SignalVote:
    raw_action = {1: SignalAction.BUY, -1: SignalAction.SELL, 0: SignalAction.HOLD}[direction]
    return SignalVote(strategy=strategy, direction=direction, confidence=confidence, raw_action=raw_action)


def _report(net_score: float, agreement_ratio=0.8, voting_strategies=3) -> ConflictReport:
    return ConflictReport(
        net_score=net_score,
        agreement_ratio=agreement_ratio,
        voting_strategies=voting_strategies,
        buy_weight=0.6,
        sell_weight=0.1,
        hold_weight=0.3,
    )


def test_decide_buy_above_threshold(settings):
    engine = ConflictResolutionEngine(settings)
    assert engine.decide(_report(net_score=0.5)) == SignalAction.BUY


def test_decide_sell_below_threshold(settings):
    engine = ConflictResolutionEngine(settings)
    assert engine.decide(_report(net_score=-0.5)) == SignalAction.SELL


def test_decide_hold_in_neutral_band(settings):
    engine = ConflictResolutionEngine(settings)
    assert engine.decide(_report(net_score=0.05)) == SignalAction.HOLD
    assert engine.decide(_report(net_score=-0.05)) == SignalAction.HOLD


def test_decide_boundary_exactly_at_threshold(settings):
    engine = ConflictResolutionEngine(settings)
    assert engine.decide(_report(net_score=settings.BUY_THRESHOLD)) == SignalAction.BUY
    assert engine.decide(_report(net_score=settings.SELL_THRESHOLD)) == SignalAction.SELL


def test_contributors_matches_brief_worked_example(settings):
    """trend BUY, mean_reversion SELL, ML BUY, breakout BUY -> final BUY -> mean_reversion excluded."""
    votes = [
        _vote("trend_following", 1, 0.80),
        _vote("mean_reversion", -1, 0.55),
        _vote("ml_prediction", 1, 0.90),
        _vote("breakout", 1, 0.75),
    ]
    engine = ConflictResolutionEngine(settings)
    contributors = engine.contributors(votes, SignalAction.BUY)
    assert set(contributors) == {"trend_following", "ml_prediction", "breakout"}
    assert "mean_reversion" not in contributors


def test_contributors_excludes_low_confidence_agreeing_strategy(settings):
    votes = [
        _vote("trend_following", 1, 0.80),
        _vote("breakout", 1, 0.10),  # agrees with BUY but confidence too low to count
    ]
    engine = ConflictResolutionEngine(settings)
    contributors = engine.contributors(votes, SignalAction.BUY)
    assert contributors == ["trend_following"]


def test_contributors_for_hold_returns_hold_voters(settings):
    votes = [
        _vote("trend_following", 0, 0.80),
        _vote("breakout", 1, 0.60),
    ]
    engine = ConflictResolutionEngine(settings)
    contributors = engine.contributors(votes, SignalAction.HOLD)
    assert contributors == ["trend_following"]
