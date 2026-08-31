from __future__ import annotations

import re

SYMBOL_PATTERN = r"^[A-Z0-9&.\-]{1,32}$"
TIMEFRAME_PATTERN = r"^[0-9]{1,4}(m|h|d|w)$|^1d$|^1w$"
STRATEGY_NAME_PATTERN = r"^[a-zA-Z0-9_\-]{1,64}$"

_symbol_re = re.compile(SYMBOL_PATTERN)
_timeframe_re = re.compile(TIMEFRAME_PATTERN)
_strategy_re = re.compile(STRATEGY_NAME_PATTERN)


def validate_symbol(symbol: str) -> str:
    if not _symbol_re.match(symbol):
        raise ValueError(f"Invalid symbol: {symbol!r}")
    return symbol


def validate_timeframe(timeframe: str) -> str:
    if not _timeframe_re.match(timeframe):
        raise ValueError(f"Invalid timeframe: {timeframe!r}")
    return timeframe


def validate_strategy_name(name: str) -> str:
    if not _strategy_re.match(name):
        raise ValueError(f"Invalid strategy name: {name!r}")
    return name
