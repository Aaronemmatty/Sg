from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.transitions import TransitionDetector
from app.models.domain import RegimeResult, RegimeType


def _result(regime: RegimeType, confidence: float, ts: datetime, symbol: str = "NIFTY50") -> RegimeResult:
    return RegimeResult(
        regime=regime,
        confidence=confidence,
        sub_regimes=[],
        symbol=symbol,
        timeframe="5m",
        timestamp=ts,
        features={"adx": 10.0},
    )


def test_first_observation_never_transitions():
    detector = TransitionDetector(confirm_bars=2, min_confidence=0.5)
    now = datetime.now(timezone.utc)
    result = _result(RegimeType.TRENDING, 0.9, now)
    assert detector.evaluate(None, result) is None


def test_same_regime_never_transitions():
    detector = TransitionDetector(confirm_bars=1, min_confidence=0.5)
    now = datetime.now(timezone.utc)
    prev = _result(RegimeType.TRENDING, 0.9, now)
    candidate = _result(RegimeType.TRENDING, 0.95, now + timedelta(minutes=5))
    assert detector.evaluate(prev, candidate) is None


def test_low_confidence_flip_does_not_transition():
    detector = TransitionDetector(confirm_bars=1, min_confidence=0.6)
    now = datetime.now(timezone.utc)
    prev = _result(RegimeType.TRENDING, 0.9, now)
    candidate = _result(RegimeType.RANGING, 0.4, now + timedelta(minutes=5))
    assert detector.evaluate(prev, candidate) is None


def test_confirmed_transition_after_required_bars():
    detector = TransitionDetector(confirm_bars=2, min_confidence=0.5)
    now = datetime.now(timezone.utc)
    prev = _result(RegimeType.TRENDING, 0.9, now)

    candidate1 = _result(RegimeType.RANGING, 0.7, now + timedelta(minutes=5))
    assert detector.evaluate(prev, candidate1) is None  # first flip candidate, not yet confirmed

    candidate2 = _result(RegimeType.RANGING, 0.75, now + timedelta(minutes=10))
    transition = detector.evaluate(prev, candidate2)
    assert transition is not None
    assert transition.from_regime == RegimeType.TRENDING
    assert transition.to_regime == RegimeType.RANGING


def test_flip_flop_resets_debounce_counter():
    detector = TransitionDetector(confirm_bars=2, min_confidence=0.5)
    now = datetime.now(timezone.utc)
    prev = _result(RegimeType.TRENDING, 0.9, now)

    # First bar suggests RANGING...
    detector.evaluate(prev, _result(RegimeType.RANGING, 0.7, now + timedelta(minutes=5)))
    # ...but the next bar flips to HIGH_VOLATILITY instead, resetting the RANGING streak.
    result = detector.evaluate(prev, _result(RegimeType.HIGH_VOLATILITY, 0.7, now + timedelta(minutes=10)))
    assert result is None  # HIGH_VOLATILITY only has 1 confirmation so far


def test_trigger_reason_volatility_shift():
    detector = TransitionDetector(confirm_bars=1, min_confidence=0.5)
    now = datetime.now(timezone.utc)
    prev = _result(RegimeType.TRENDING, 0.9, now)
    candidate = _result(RegimeType.HIGH_VOLATILITY, 0.8, now + timedelta(minutes=5))
    transition = detector.evaluate(prev, candidate)
    assert transition.trigger_reason == "volatility_shift"


def test_trigger_reason_structure_flip():
    detector = TransitionDetector(confirm_bars=1, min_confidence=0.5)
    now = datetime.now(timezone.utc)
    prev = _result(RegimeType.TRENDING, 0.9, now)
    candidate = _result(RegimeType.RANGING, 0.8, now + timedelta(minutes=5))
    transition = detector.evaluate(prev, candidate)
    assert transition.trigger_reason == "structure_flip"


def test_per_symbol_state_is_independent():
    detector = TransitionDetector(confirm_bars=1, min_confidence=0.5)
    now = datetime.now(timezone.utc)
    prev_a = _result(RegimeType.TRENDING, 0.9, now, symbol="NIFTY50")
    prev_b = _result(RegimeType.RANGING, 0.9, now, symbol="RELIANCE")

    transition_a = detector.evaluate(
        prev_a, _result(RegimeType.RANGING, 0.8, now + timedelta(minutes=5), symbol="NIFTY50")
    )
    transition_b = detector.evaluate(
        prev_b, _result(RegimeType.TRENDING, 0.8, now + timedelta(minutes=5), symbol="RELIANCE")
    )
    assert transition_a is not None and transition_a.symbol == "NIFTY50"
    assert transition_b is not None and transition_b.symbol == "RELIANCE"
