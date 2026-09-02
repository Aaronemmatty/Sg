"""Shared security, calendar, CORS, and universe helpers for SG services."""

from sg_security.calendar import (
    IST,
    MARKET_CLOSE,
    MARKET_OPEN,
    NSE_HOLIDAYS,
    PREOPEN_START,
    candle_start,
    candle_start_epoch,
    ensure_ist,
    is_market_open,
    is_preopen,
    is_trading_day,
    now_ist,
    seconds_to_market_open,
)
from sg_security.cors import parse_cors_origins
from sg_security.env import is_development, is_production, is_staging
from sg_security.jwt_auth import (
    CurrentUser,
    JWTAuthConfig,
    JWTAuthDependencies,
)
from sg_security.universe import (
    filter_universe,
    get_nifty200_base_prices,
    get_nifty200_symbols,
    get_nifty200_token_map,
    get_tradeable_universe,
    refresh_universe,
)

__all__ = [
    "IST",
    "MARKET_CLOSE",
    "MARKET_OPEN",
    "NSE_HOLIDAYS",
    "PREOPEN_START",
    "candle_start",
    "candle_start_epoch",
    "ensure_ist",
    "is_market_open",
    "is_preopen",
    "is_trading_day",
    "now_ist",
    "seconds_to_market_open",
    "parse_cors_origins",
    "is_development",
    "is_production",
    "is_staging",
    "CurrentUser",
    "JWTAuthConfig",
    "JWTAuthDependencies",
    "get_nifty200_symbols",
    "get_nifty200_token_map",
    "get_nifty200_base_prices",
    "get_tradeable_universe",
    "filter_universe",
    "refresh_universe",
]
