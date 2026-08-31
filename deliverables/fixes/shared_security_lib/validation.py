"""
shared_security_lib/validation.py — input validation for the path/query
parameters that are currently typed as bare `str` across every service
(symbol, strategy, timeframe) and used directly to build:
  - outbound REST paths to market_data_service (e.g. f"/symbols/{symbol}/ltp")
  - Redis keys (e.g. f"signal:{strategy}:{symbol}:{timeframe}")

See DATA_PROTECTION.md / OWASP_ANALYSIS.md (API3:2023 — Broken Object
Property Level Authorization / injection-adjacent input validation gap)
for why this matters even though no full SQL/SSRF injection was found:
an unvalidated `symbol` containing `/`, `:`, or `..` can cross into Redis
key namespaces it shouldn't reach (key-injection) or, for the path-built
REST calls, traverse to unintended paths on an internal trusted service.
Neither is currently exploitable into something catastrophic given the
internal trust boundary, but both are free to close and remove the
question entirely.

Usage with FastAPI path/query params:

    from fastapi import Path
    from shared_security_lib.validation import SYMBOL_PATTERN

    @router.get("/{symbol}")
    async def get_signal(symbol: str = Path(..., pattern=SYMBOL_PATTERN)):
        ...

Or, for use deeper in the call stack (e.g. inside a Redis client) where a
FastAPI Path() constraint isn't available:

    from shared_security_lib.validation import validate_symbol

    def get_signal(symbol: str) -> ...:
        symbol = validate_symbol(symbol)  # raises ValueError if invalid
        ...
"""
from __future__ import annotations

import re

# NSE/BSE equity symbols are uppercase alphanumerics plus a small set of
# punctuation used in actual instrument names (e.g. "M&M", "L&T",
# "BAJAJ-AUTO"). Adjust if your instrument universe needs more, but keep
# it an explicit allow-list rather than a deny-list of bad characters.
SYMBOL_PATTERN = r"^[A-Z0-9&.\-]{1,32}$"
TIMEFRAME_PATTERN = r"^[0-9]{1,4}(m|h|d|w)$|^1d$|^1w$"  # e.g. "5m", "1h", "1d"
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
