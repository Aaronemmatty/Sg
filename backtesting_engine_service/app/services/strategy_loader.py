from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

import httpx
import numpy as np
import pandas as pd
import tenacity

from app.core.config import settings
from app.core.logging import log
from app.models.domain import StrategyRef, StrategySourceType

Signal = Literal["BUY", "SELL", "HOLD"]


class StrategyLoadError(Exception):
    pass


class SignalProvider(ABC):
    """Common interface the backtest engine drives bar-by-bar."""

    @abstractmethod
    async def prepare(self, symbol: str, bars: pd.DataFrame) -> None:
        """Pre-compute indicators / warm up state for the full series."""

    @abstractmethod
    def signal_at(self, symbol: str, idx: int) -> Signal:
        """Return BUY / SELL / HOLD for bar index `idx` (no look-ahead)."""

    async def aclose(self) -> None:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRY provider — defers to strategy_service (8004)
# ─────────────────────────────────────────────────────────────────────────────

class RegistryStrategyProvider(SignalProvider):
    """Calls strategy_service for signals on a registered StrategyBase strategy.

    Contract assumption (isolated here, same pattern as data_loader.py):
    POST /api/v1/strategies/{name}/evaluate
      body: {"symbol": str, "bars": [{ts, open, high, low, close, volume}, ...], "params": {...}}
      resp: {"signals": ["BUY"|"SELL"|"HOLD", ...]}   (one per input bar, no look-ahead)

    If strategy_service is unreachable, the backtest fails fast rather than
    silently falling back — unlike market data, trading logic correctness
    must not degrade silently.
    """

    def __init__(self, ref: StrategyRef, client: httpx.AsyncClient | None = None) -> None:
        if not ref.name:
            raise StrategyLoadError("StrategyRef.name is required for source=registry")
        self._ref = ref
        self._client = client or httpx.AsyncClient(
            base_url=settings.strategy_service_url,
            timeout=settings.http_client_timeout_seconds,
        )
        self._signals: dict[str, list[Signal]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=0.5, max=4),
        retry=tenacity.retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    async def prepare(self, symbol: str, bars: pd.DataFrame) -> None:
        payload = {
            "symbol": symbol,
            "bars": [
                {
                    "ts": row.ts.isoformat(),
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                }
                for row in bars.itertuples(index=False)
            ],
            "params": self._ref.params,
        }
        try:
            resp = await self._client.post(
                f"/api/v1/strategies/{self._ref.name}/evaluate", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            signals = data.get("signals", [])
        except httpx.HTTPError as exc:
            raise StrategyLoadError(
                f"strategy_service evaluate call failed for '{self._ref.name}': {exc}"
            ) from exc

        if len(signals) != len(bars):
            log.warning(
                "strategy_signal_length_mismatch",
                expected=len(bars),
                received=len(signals),
                strategy=self._ref.name,
            )
        # Pad/truncate defensively so the engine never indexes out of range.
        padded = (list(signals) + ["HOLD"] * len(bars))[: len(bars)]
        self._signals[symbol] = [s if s in ("BUY", "SELL", "HOLD") else "HOLD" for s in padded]

    def signal_at(self, symbol: str, idx: int) -> Signal:
        return self._signals.get(symbol, [])[idx] if idx < len(self._signals.get(symbol, [])) else "HOLD"


# ─────────────────────────────────────────────────────────────────────────────
# INLINE provider — self-contained, no 8004 dependency
# ─────────────────────────────────────────────────────────────────────────────

_SUPPORTED_INDICATORS = {"sma", "ema", "rsi"}
_SUPPORTED_OPS = {"gt", "lt", "gte", "lte", "eq", "cross_above", "cross_below"}


class InlineRuleStrategyProvider(SignalProvider):
    """Evaluates a constrained, declarative rule set — no arbitrary code
    execution. Supported indicators: sma, ema, rsi. Conditions compare two
    named series (an indicator or 'close') with gt/lt/gte/lte/eq/cross_above/
    cross_below.

    Example inline_rules:
      {
        "indicators": {
          "fast": {"type": "sma", "period": 10},
          "slow": {"type": "sma", "period": 50}
        },
        "entry_long":  {"left": "fast", "op": "cross_above", "right": "slow"},
        "exit_long":   {"left": "fast", "op": "cross_below", "right": "slow"}
      }
    """

    def __init__(self, ref: StrategyRef) -> None:
        if not ref.inline_rules:
            raise StrategyLoadError("StrategyRef.inline_rules is required for source=inline")
        self._rules = ref.inline_rules
        self._series: dict[str, dict[str, pd.Series]] = {}
        self._validate()

    def _validate(self) -> None:
        for indicator_name, spec in self._rules.get("indicators", {}).items():
            itype = spec.get("type")
            if itype not in _SUPPORTED_INDICATORS:
                raise StrategyLoadError(
                    f"Unsupported indicator type '{itype}' for '{indicator_name}'. "
                    f"Supported: {sorted(_SUPPORTED_INDICATORS)}"
                )
        for key in ("entry_long", "exit_long"):
            cond = self._rules.get(key)
            if cond and cond.get("op") not in _SUPPORTED_OPS:
                raise StrategyLoadError(
                    f"Unsupported op '{cond.get('op')}' in '{key}'. "
                    f"Supported: {sorted(_SUPPORTED_OPS)}"
                )

    async def prepare(self, symbol: str, bars: pd.DataFrame) -> None:
        close = bars["close"]
        series: dict[str, pd.Series] = {"close": close}

        for name, spec in self._rules.get("indicators", {}).items():
            itype = spec["type"]
            period = int(spec.get("period", 14))
            if itype == "sma":
                series[name] = close.rolling(window=period, min_periods=period).mean()
            elif itype == "ema":
                series[name] = close.ewm(span=period, adjust=False).mean()
            elif itype == "rsi":
                series[name] = self._rsi(close, period)

        self._series[symbol] = series

    @staticmethod
    def _rsi(close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)

    def _eval_condition(self, symbol: str, cond: dict[str, Any], idx: int) -> bool:
        series = self._series[symbol]
        left = series.get(cond["left"])
        right_key = cond["right"]
        right = series.get(right_key) if isinstance(right_key, str) and right_key in series else None
        if left is None:
            return False

        l_now = left.iloc[idx]
        r_now = right.iloc[idx] if right is not None else float(right_key)
        if pd.isna(l_now) or pd.isna(r_now):
            return False

        op = cond["op"]
        if op == "gt":
            return l_now > r_now
        if op == "lt":
            return l_now < r_now
        if op == "gte":
            return l_now >= r_now
        if op == "lte":
            return l_now <= r_now
        if op == "eq":
            return l_now == r_now
        if op in ("cross_above", "cross_below"):
            if idx == 0:
                return False
            l_prev = left.iloc[idx - 1]
            r_prev = right.iloc[idx - 1] if right is not None else float(right_key)
            if pd.isna(l_prev) or pd.isna(r_prev):
                return False
            if op == "cross_above":
                return l_prev <= r_prev and l_now > r_now
            return l_prev >= r_prev and l_now < r_now
        return False

    def signal_at(self, symbol: str, idx: int) -> Signal:
        entry = self._rules.get("entry_long")
        exit_ = self._rules.get("exit_long")
        if entry and self._eval_condition(symbol, entry, idx):
            return "BUY"
        if exit_ and self._eval_condition(symbol, exit_, idx):
            return "SELL"
        return "HOLD"


def build_signal_provider(ref: StrategyRef) -> SignalProvider:
    if ref.source == StrategySourceType.REGISTRY:
        return RegistryStrategyProvider(ref)
    if ref.source == StrategySourceType.INLINE:
        return InlineRuleStrategyProvider(ref)
    raise StrategyLoadError(f"Unknown strategy source: {ref.source}")
