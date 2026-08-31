"""
Technical feature engineering for regime classification.

All functions operate on a pandas DataFrame with columns: open, high, low, close, volume,
indexed by ascending timestamp. Implementations follow standard Wilder's smoothing for
ADX/ATR. No external TA library dependency is required, keeping the service's footprint
small and the math auditable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.config import Settings
from app.models.domain import FeatureSet

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def _validate(df: pd.DataFrame, min_bars: int) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV dataframe missing required columns: {missing}")
    if len(df) < min_bars:
        raise ValueError(f"Need at least {min_bars} bars, got {len(df)}")


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def average_true_range(df: pd.DataFrame, period: int) -> pd.Series:
    tr = true_range(df)
    # Wilder's smoothing (equivalent to EMA with alpha = 1/period)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int) -> pd.Series:
    """Average Directional Index via Wilder's method."""
    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(df)
    atr_ = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()

    plus_dm_s = pd.Series(plus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean()
    minus_dm_s = pd.Series(minus_dm, index=df.index).ewm(
        alpha=1.0 / period, adjust=False, min_periods=period
    ).mean()

    # Avoid div-by-zero
    atr_safe = atr_.replace(0, np.nan)
    plus_di = 100 * (plus_dm_s / atr_safe)
    minus_di = 100 * (minus_dm_s / atr_safe)

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx_series = dx.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    return adx_series.fillna(0.0)


def bollinger_band_width(df: pd.DataFrame, period: int, num_std: float) -> pd.Series:
    mid = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid.replace(0, np.nan)
    return width.fillna(0.0)


def volume_ratio(df: pd.DataFrame, period: int) -> pd.Series:
    avg_vol = df["volume"].rolling(period).mean().replace(0, np.nan)
    return (df["volume"] / avg_vol).fillna(1.0)


def trend_slope(df: pd.DataFrame, period: int) -> pd.Series:
    """
    Normalized linear-regression slope of close over a rolling window, expressed as
    %-change-per-bar relative to the window's mean price (so it is comparable across
    symbols at different price levels).
    """
    x = np.arange(period)
    x_mean = x.mean()
    x_demeaned = x - x_mean
    denom = (x_demeaned**2).sum()

    def _slope(window: np.ndarray) -> float:
        y_mean = window.mean()
        if y_mean == 0:
            return 0.0
        slope = (x_demeaned * (window - y_mean)).sum() / denom
        return float(slope / y_mean)

    return df["close"].rolling(period).apply(_slope, raw=True).fillna(0.0)


def realized_vol(df: pd.DataFrame, period: int) -> pd.Series:
    log_ret = np.log(df["close"] / df["close"].shift(1))
    return log_ret.rolling(period).std(ddof=0).fillna(0.0)


def compute_feature_set(
    df: pd.DataFrame,
    settings: Settings,
    vix_value: float | None = None,
    breadth_pct: float | None = None,
) -> FeatureSet:
    """
    Compute the latest (most recent bar) FeatureSet from an OHLCV DataFrame.
    `df` must be sorted ascending by time and contain at least `settings.MIN_BARS_REQUIRED` rows.
    """
    _validate(df, settings.MIN_BARS_REQUIRED)

    atr_series = average_true_range(df, settings.ATR_PERIOD)
    adx_series = adx(df, settings.ADX_PERIOD)
    bb_series = bollinger_band_width(df, settings.BB_PERIOD, settings.BB_STD)
    vol_ratio_series = volume_ratio(df, settings.VOLUME_AVG_PERIOD)
    slope_series = trend_slope(df, settings.TREND_SLOPE_PERIOD)
    rvol_series = realized_vol(df, settings.RETURNS_STD_PERIOD)

    last_close = float(df["close"].iloc[-1])
    last_atr = float(atr_series.iloc[-1])

    return FeatureSet(
        adx=float(adx_series.iloc[-1]),
        atr=last_atr,
        atr_pct=float(last_atr / last_close) if last_close else 0.0,
        bb_width=float(bb_series.iloc[-1]),
        volume_ratio=float(vol_ratio_series.iloc[-1]),
        trend_slope=float(slope_series.iloc[-1]),
        returns_std=float(rvol_series.iloc[-1]),
        vix_proxy=vix_value,
        breadth_pct=breadth_pct,
        close=last_close,
    )


def compute_feature_frame(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """
    Vectorized feature computation over the *entire* history (used for training and
    backtesting, where we need a feature row per historical bar, not just the latest one).
    """
    _validate(df, settings.MIN_BARS_REQUIRED)

    out = pd.DataFrame(index=df.index)
    out["adx"] = adx(df, settings.ADX_PERIOD)
    atr_series = average_true_range(df, settings.ATR_PERIOD)
    out["atr"] = atr_series
    out["atr_pct"] = (atr_series / df["close"].replace(0, np.nan)).fillna(0.0)
    out["bb_width"] = bollinger_band_width(df, settings.BB_PERIOD, settings.BB_STD)
    out["volume_ratio"] = volume_ratio(df, settings.VOLUME_AVG_PERIOD)
    out["trend_slope"] = trend_slope(df, settings.TREND_SLOPE_PERIOD)
    out["returns_std"] = realized_vol(df, settings.RETURNS_STD_PERIOD)
    out["close"] = df["close"]
    return out.iloc[settings.MIN_BARS_REQUIRED - 1 :]
