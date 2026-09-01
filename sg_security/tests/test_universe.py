import pytest
from sg_security.universe import (
    get_nifty200_symbols,
    get_nifty200_token_map,
    get_nifty200_base_prices,
    get_tradeable_universe,
    filter_universe,
)


def test_nifty200_symbols():
    symbols_prefixed = get_nifty200_symbols(prefix=True)
    symbols_bare = get_nifty200_symbols(prefix=False)

    assert len(symbols_prefixed) == 200
    assert len(symbols_bare) == 200
    assert all(s.startswith("NSE:") for s in symbols_prefixed)
    assert not any(s.startswith("NSE:") for s in symbols_bare)
    assert "NSE:RELIANCE" in symbols_prefixed
    assert "RELIANCE" in symbols_bare


def test_token_map_and_base_prices():
    token_map = get_nifty200_token_map(prefix=True)
    base_prices = get_nifty200_base_prices(prefix=True)

    assert len(token_map) == 200
    assert len(base_prices) == 200
    assert "NSE:RELIANCE" in token_map
    assert token_map["NSE:RELIANCE"] > 0
    assert base_prices["NSE:RELIANCE"] > 0


def test_tradeable_universe():
    tradeable_bare = get_tradeable_universe(prefix=False)
    tradeable_prefixed = get_tradeable_universe(prefix=True)

    assert len(tradeable_bare) > 0
    assert len(tradeable_bare) == len(tradeable_prefixed)
    assert "RELIANCE" not in tradeable_bare  # > ₹500
    assert "TCS" not in tradeable_bare       # > ₹500
    assert "TATASTEEL" in tradeable_bare    # < ₹500 & high liquidity
    assert "ITC" in tradeable_bare          # < ₹500 & high liquidity
    assert "WIPRO" in tradeable_bare        # < ₹500 & high liquidity


def test_filter_universe_dynamic():
    custom_symbols = ["NSE:RELIANCE", "NSE:TATASTEEL", "NSE:ILLIQUID_TEST"]
    price_map = {
        "NSE:RELIANCE": 2900.0,
        "NSE:TATASTEEL": 180.0,
        "NSE:ILLIQUID_TEST": 50.0,
    }
    volume_map = {
        "NSE:RELIANCE": 5_000_000,
        "NSE:TATASTEEL": 10_000_000,
        "NSE:ILLIQUID_TEST": 100,  # Below liquidity volume threshold
    }

    filtered = filter_universe(
        symbols=custom_symbols,
        price_map=price_map,
        volume_map=volume_map,
        max_price=500.0,
        min_adtv_inr=250_000_000.0,
        min_volume=500_000,
        prefix=True,
    )

    assert filtered == ["NSE:TATASTEEL"]
