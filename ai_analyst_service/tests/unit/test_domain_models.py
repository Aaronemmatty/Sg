from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.domain import MarketSummaryRequest, TradeReviewRequest


def test_trade_review_request_defaults():
    req = TradeReviewRequest()
    assert req.lookback_days == 7
    assert req.stream is False
    assert req.user_note is None


def test_trade_review_request_strips_user_note_whitespace():
    req = TradeReviewRequest(user_note="  please explain clearly  ")
    assert req.user_note == "please explain clearly"


def test_trade_review_request_rejects_too_long_note():
    with pytest.raises(ValidationError):
        TradeReviewRequest(user_note="x" * 10_000)


def test_trade_review_request_rejects_excessive_lookback():
    with pytest.raises(ValidationError):
        TradeReviewRequest(lookback_days=365)


def test_market_summary_request_requires_at_least_one_symbol():
    with pytest.raises(ValidationError):
        MarketSummaryRequest(symbols=[])


def test_market_summary_request_caps_symbol_count():
    with pytest.raises(ValidationError):
        MarketSummaryRequest(symbols=[f"SYM{i}" for i in range(25)])


def test_market_summary_request_accepts_valid_symbols():
    req = MarketSummaryRequest(symbols=["RELIANCE", "TCS"])
    assert req.symbols == ["RELIANCE", "TCS"]
