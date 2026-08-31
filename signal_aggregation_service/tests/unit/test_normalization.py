from __future__ import annotations

from app.core.normalization import coerce_action, normalize_signal, normalize_signal_allow_stale
from app.models.domain import SignalAction
from tests.conftest import make_raw_signal


def test_normalize_buy_signal(settings):
    raw = make_raw_signal("trend_following", action="BUY", confidence=0.8)
    vote = normalize_signal(raw, settings)
    assert vote is not None
    assert vote.direction == 1
    assert vote.confidence == 0.8
    assert vote.raw_action == SignalAction.BUY
    assert vote.signed_strength == 0.8


def test_normalize_sell_signal(settings):
    raw = make_raw_signal("mean_reversion", action="SELL", confidence=0.55)
    vote = normalize_signal(raw, settings)
    assert vote.direction == -1
    assert vote.signed_strength == -0.55


def test_normalize_hold_signal(settings):
    raw = make_raw_signal("rsi", action="HOLD", confidence=0.3)
    vote = normalize_signal(raw, settings)
    assert vote.direction == 0
    assert vote.signed_strength == 0.0


def test_normalize_returns_none_for_malformed_payload(settings):
    assert normalize_signal({"garbage": True}, settings) is None
    assert normalize_signal({}, settings) is None


def test_normalize_returns_none_for_stale_signal(settings):
    raw = make_raw_signal("trend_following", age_seconds=settings.SIGNAL_STALENESS_SECONDS + 100)
    assert normalize_signal(raw, settings) is None


def test_normalize_allow_stale_returns_vote_flagged_stale(settings):
    raw = make_raw_signal("trend_following", age_seconds=settings.SIGNAL_STALENESS_SECONDS + 100)
    vote = normalize_signal_allow_stale(raw, settings)
    assert vote is not None
    assert vote.is_stale is True


def test_normalize_fresh_signal_not_flagged_stale(settings):
    raw = make_raw_signal("trend_following", age_seconds=5)
    vote = normalize_signal_allow_stale(raw, settings)
    assert vote.is_stale is False


def test_coerce_action_aliases():
    assert coerce_action("buy") == SignalAction.BUY
    assert coerce_action("LONG") == SignalAction.BUY
    assert coerce_action("Short") == SignalAction.SELL
    assert coerce_action("neutral") == SignalAction.HOLD
    assert coerce_action(0.5) == SignalAction.BUY
    assert coerce_action(-0.5) == SignalAction.SELL
    assert coerce_action(0) == SignalAction.HOLD
    assert coerce_action("nonsense") is None
    assert coerce_action(None) is None
