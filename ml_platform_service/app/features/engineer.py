"""
Feature Engineering Pipeline.

Computes the full FeatureVector from raw OHLCV data.
Designed to be called:
  1. In the real-time path (on each new candle from Redis)
  2. In the training path (over historical OHLCV batches)

All computations are pure numpy/pandas — no external calls.
NaN values are forward-filled then zero-filled — model inputs are always finite.

Indicators implemented (no TA-Lib dependency):
  Returns, SMA, EMA, RSI, MACD, Stochastic, ATR, Bollinger Bands,
  Realized Vol, OBV, VWAP approximation, price structure, time features.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.core.metrics import feature_computation_errors, feature_computation_latency, feature_computation_total
from app.models.domain import FeatureBatch, FeatureVector

log = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Low-level indicator functions (vectorized, operate on Series/arrays)
# ─────────────────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    hl = high - low
    hc = (high - close.shift()).abs()
    lc = (low - close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _bollinger(close: pd.Series, period: int = 20, std_dev: float = 2.0):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    width = (upper - lower) / sma.replace(0, np.nan)
    pct = (close - lower) / (upper - lower).replace(0, np.nan)
    return upper, lower, width, pct


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                k_period: int = 14, d_period: int = 3):
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    denom = (highest_high - lowest_low).replace(0, np.nan)
    k = (close - lowest_low) / denom * 100
    d = k.rolling(d_period).mean()
    return k, d


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def _vwap_approx(high: pd.Series, low: pd.Series, close: pd.Series,
                 volume: pd.Series, period: int = 20) -> pd.Series:
    """Rolling VWAP approximation (true VWAP requires tick data)."""
    typical = (high + low + close) / 3
    return (typical * volume).rolling(period).sum() / volume.rolling(period).sum().replace(0, np.nan)


def _realized_vol(close: pd.Series, period: int) -> pd.Series:
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(period).std() * np.sqrt(252)


# ─────────────────────────────────────────────────────────────────────────────
# Main feature engineering class
# ─────────────────────────────────────────────────────────────────────────────

class FeatureEngineer:
    """
    Stateless feature engineer. Call compute_dataframe() to get a full
    feature matrix from raw OHLCV data, or compute_latest() for a single
    FeatureVector from the most recent bar.
    """

    def compute_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all features over a full OHLCV DataFrame.

        Args:
            df: DataFrame with columns [open, high, low, close, volume]
                and a DatetimeIndex.

        Returns:
            DataFrame with all feature columns appended.
            Rows with insufficient history are dropped.
        """
        if len(df) < 50:
            raise ValueError(f"Need at least 50 bars, got {len(df)}")

        out = df.copy()
        c, h, l, v = out["close"], out["high"], out["low"], out["volume"]

        # Log returns
        log_c = np.log(c)
        out["ret_1"] = log_c.diff(1)
        out["ret_5"] = log_c.diff(5)
        out["ret_10"] = log_c.diff(10)
        out["ret_20"] = log_c.diff(20)

        # Moving averages
        for p in [5, 10, 20, 50]:
            out[f"sma_{p}"] = c.rolling(p).mean()
        out["ema_12"] = _ema(c, 12)
        out["ema_26"] = _ema(c, 26)

        # MACD
        macd = out["ema_12"] - out["ema_26"]
        macd_signal = _ema(macd, 9)
        out["macd"] = macd
        out["macd_signal"] = macd_signal
        out["macd_hist"] = macd - macd_signal

        # RSI
        out["rsi_14"] = _rsi(c, 14)

        # Stochastic
        out["stoch_k"], out["stoch_d"] = _stochastic(h, l, c)

        # ATR
        out["atr_14"] = _atr(h, l, c, 14)

        # Bollinger Bands
        out["bb_upper"], out["bb_lower"], out["bb_width"], out["bb_pct"] = _bollinger(c)

        # Realized volatility
        out["realized_vol_5"] = _realized_vol(c, 5)
        out["realized_vol_20"] = _realized_vol(c, 20)

        # Volume features
        out["vol_sma_20"] = v.rolling(20).mean()
        out["vol_ratio"] = v / out["vol_sma_20"].replace(0, np.nan)
        out["obv"] = _obv(c, v)
        out["vwap"] = _vwap_approx(h, l, c, v)

        # Price structure
        out["high_20"] = h.rolling(20).max()
        out["low_20"] = l.rolling(20).min()
        out["pct_from_high_20"] = (c - out["high_20"]) / out["high_20"].replace(0, np.nan)
        out["pct_from_low_20"] = (c - out["low_20"]) / out["low_20"].replace(0, np.nan)

        # Regime placeholders (filled by consumer when regime data available)
        if "regime_trend" not in out.columns:
            out["regime_trend"] = 0.5
        if "regime_vol" not in out.columns:
            out["regime_vol"] = 0.5

        # Time features
        if hasattr(out.index, "hour"):
            out["hour"] = out.index.hour
            out["day_of_week"] = out.index.dayofweek
            out["is_monday"] = (out.index.dayofweek == 0).astype(int)
            out["is_friday"] = (out.index.dayofweek == 4).astype(int)
        else:
            out["hour"] = 9
            out["day_of_week"] = 0
            out["is_monday"] = 0
            out["is_friday"] = 0

        # Forward-fill then zero-fill NaNs
        out = out.ffill().fillna(0)

        # Drop rows where we definitely have no usable data (first 50 bars)
        out = out.iloc[50:].copy()
        return out

    def compute_latest(
        self,
        df: pd.DataFrame,
        symbol: str,
        regime_trend: float = 0.5,
        regime_vol: float = 0.5,
    ) -> FeatureVector:
        """
        Compute FeatureVector for the most recent bar in df.
        df must have at least 50 bars.
        """
        t0 = time.perf_counter()
        try:
            df = df.copy()
            df["regime_trend"] = regime_trend
            df["regime_vol"] = regime_vol
            feat_df = self.compute_dataframe(df)
            if len(feat_df) == 0:
                raise ValueError("No feature rows after computation")
            row = feat_df.iloc[-1]
            ts = feat_df.index[-1]
            if not isinstance(ts, datetime):
                ts = datetime.now(timezone.utc)

            fv = FeatureVector(
                symbol=symbol,
                timestamp=ts,
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("volume", 0)),
                ret_1=float(row.get("ret_1", 0)),
                ret_5=float(row.get("ret_5", 0)),
                ret_10=float(row.get("ret_10", 0)),
                ret_20=float(row.get("ret_20", 0)),
                sma_5=float(row.get("sma_5", 0)),
                sma_10=float(row.get("sma_10", 0)),
                sma_20=float(row.get("sma_20", 0)),
                sma_50=float(row.get("sma_50", 0)),
                ema_12=float(row.get("ema_12", 0)),
                ema_26=float(row.get("ema_26", 0)),
                rsi_14=float(row.get("rsi_14", 50)),
                macd=float(row.get("macd", 0)),
                macd_signal=float(row.get("macd_signal", 0)),
                macd_hist=float(row.get("macd_hist", 0)),
                stoch_k=float(row.get("stoch_k", 50)),
                stoch_d=float(row.get("stoch_d", 50)),
                atr_14=float(row.get("atr_14", 0)),
                bb_upper=float(row.get("bb_upper", 0)),
                bb_lower=float(row.get("bb_lower", 0)),
                bb_width=float(row.get("bb_width", 0)),
                bb_pct=float(row.get("bb_pct", 0.5)),
                realized_vol_5=float(row.get("realized_vol_5", 0)),
                realized_vol_20=float(row.get("realized_vol_20", 0)),
                vol_sma_20=float(row.get("vol_sma_20", 0)),
                vol_ratio=float(row.get("vol_ratio", 1)),
                obv=float(row.get("obv", 0)),
                vwap=float(row.get("vwap", 0)),
                high_20=float(row.get("high_20", 0)),
                low_20=float(row.get("low_20", 0)),
                pct_from_high_20=float(row.get("pct_from_high_20", 0)),
                pct_from_low_20=float(row.get("pct_from_low_20", 0)),
                regime_trend=regime_trend,
                regime_vol=regime_vol,
                hour=int(row.get("hour", 9)),
                day_of_week=int(row.get("day_of_week", 0)),
                is_monday=int(row.get("is_monday", 0)),
                is_friday=int(row.get("is_friday", 0)),
            )

            elapsed = time.perf_counter() - t0
            feature_computation_latency.observe(elapsed)
            feature_computation_total.labels(symbol=symbol).inc()
            return fv

        except Exception:
            feature_computation_errors.labels(symbol=symbol).inc()
            log.exception("feature_computation_failed", symbol=symbol)
            raise

    def compute_batch(self, df: pd.DataFrame, symbol: str) -> FeatureBatch:
        """
        Compute FeatureBatch (all bars) for sequence model training/inference.
        """
        feat_df = self.compute_dataframe(df)
        vectors = []
        for ts, row in feat_df.iterrows():
            if not isinstance(ts, datetime):
                ts = datetime.now(timezone.utc)
            vectors.append(FeatureVector(
                symbol=symbol,
                timestamp=ts,
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("volume", 0)),
                **{k: float(row.get(k, 0)) for k in [
                    "ret_1","ret_5","ret_10","ret_20",
                    "sma_5","sma_10","sma_20","sma_50","ema_12","ema_26",
                    "macd","macd_signal","macd_hist","stoch_k","stoch_d","atr_14",
                    "bb_upper","bb_lower","bb_width","bb_pct",
                    "realized_vol_5","realized_vol_20","vol_sma_20","vol_ratio",
                    "obv","vwap","high_20","low_20","pct_from_high_20","pct_from_low_20",
                    "regime_trend","regime_vol",
                ]},
                rsi_14=float(row.get("rsi_14", 50)),
                hour=int(row.get("hour", 9)),
                day_of_week=int(row.get("day_of_week", 0)),
                is_monday=int(row.get("is_monday", 0)),
                is_friday=int(row.get("is_friday", 0)),
            ))
        return FeatureBatch(symbol=symbol, vectors=vectors)

    @staticmethod
    def compute_target(df: pd.DataFrame, target_type: str, forward_bars: int = 5) -> pd.Series:
        """
        Compute training labels from OHLCV data.

        direction → 0=DOWN, 1=FLAT, 2=UP based on forward return threshold
        return_5bar / return_10bar → raw forward log return (regression)
        volatility → realized vol over next forward_bars bars
        """
        c = df["close"]
        fwd_return = np.log(c.shift(-forward_bars) / c)

        if target_type == "direction":
            thresh = 0.002   # 0.2% threshold for FLAT zone
            labels = pd.Series(1, index=df.index)   # default FLAT
            labels[fwd_return > thresh] = 2          # UP
            labels[fwd_return < -thresh] = 0         # DOWN
            return labels.shift(forward_bars).dropna()
        elif target_type in ("return_5bar", "return_10bar"):
            return fwd_return.shift(forward_bars).dropna()
        elif target_type == "volatility":
            log_ret = np.log(c / c.shift(1))
            fwd_vol = log_ret.rolling(forward_bars).std().shift(-forward_bars) * np.sqrt(252)
            return fwd_vol.shift(forward_bars).dropna()
        else:
            raise ValueError(f"Unknown target_type: {target_type}")


# ─────────────────────────────────────────────────────────────────────────────
# PSI (Population Stability Index) for drift detection
# ─────────────────────────────────────────────────────────────────────────────

def compute_psi(reference: np.ndarray, current: np.ndarray, n_bins: int = 10) -> float:
    """
    Compute PSI between reference distribution and current window.
    PSI < 0.1: no drift, 0.1–0.2: minor drift, > 0.2: significant drift.
    """
    eps = 1e-10
    # Use reference quantiles as bin edges
    quantiles = np.linspace(0, 100, n_bins + 1)
    bin_edges = np.percentile(reference, quantiles)
    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf

    ref_counts, _ = np.histogram(reference, bins=bin_edges)
    cur_counts, _ = np.histogram(current, bins=bin_edges)

    ref_pct = ref_counts / (len(reference) + eps)
    cur_pct = cur_counts / (len(current) + eps)

    # Clip to avoid log(0)
    ref_pct = np.clip(ref_pct, eps, None)
    cur_pct = np.clip(cur_pct, eps, None)

    psi = np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct))
    return float(psi)
