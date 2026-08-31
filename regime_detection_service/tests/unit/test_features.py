from __future__ import annotations

import pandas as pd
import pytest

from app.core.features import (
    adx,
    average_true_range,
    bollinger_band_width,
    compute_feature_frame,
    compute_feature_set,
    realized_vol,
    trend_slope,
    volume_ratio,
)


def test_atr_is_positive_and_finite(trending_ohlcv, settings):
    atr = average_true_range(trending_ohlcv, settings.ATR_PERIOD)
    tail = atr.dropna()
    assert (tail >= 0).all()
    assert tail.iloc[-1] > 0


def test_adx_in_valid_range(trending_ohlcv, settings):
    adx_series = adx(trending_ohlcv, settings.ADX_PERIOD)
    assert (adx_series >= 0).all()
    assert (adx_series <= 100).all()


def test_adx_higher_for_trending_than_ranging(trending_ohlcv, ranging_ohlcv, settings):
    trend_adx = adx(trending_ohlcv, settings.ADX_PERIOD).iloc[-1]
    range_adx = adx(ranging_ohlcv, settings.ADX_PERIOD).iloc[-1]
    assert trend_adx > range_adx


def test_bb_width_lower_for_ranging_than_trending(trending_ohlcv, ranging_ohlcv, settings):
    trend_bb = bollinger_band_width(trending_ohlcv, settings.BB_PERIOD, settings.BB_STD).iloc[-1]
    range_bb = bollinger_band_width(ranging_ohlcv, settings.BB_PERIOD, settings.BB_STD).iloc[-1]
    assert range_bb < trend_bb


def test_volume_ratio_centers_around_one_for_uniform_volume(settings):
    df = pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.0] * 30,
            "volume": [10_000] * 30,
        }
    )
    ratio = volume_ratio(df, settings.VOLUME_AVG_PERIOD)
    assert abs(ratio.iloc[-1] - 1.0) < 1e-6


def test_trend_slope_sign_matches_direction(trending_ohlcv, bearish_ohlcv, settings):
    up_slope = trend_slope(trending_ohlcv, settings.TREND_SLOPE_PERIOD).iloc[-1]
    down_slope = trend_slope(bearish_ohlcv, settings.TREND_SLOPE_PERIOD).iloc[-1]
    assert up_slope > 0
    assert down_slope < 0


def test_realized_vol_higher_for_high_vol_series(high_vol_ohlcv, ranging_ohlcv, settings):
    hv = realized_vol(high_vol_ohlcv, settings.RETURNS_STD_PERIOD).iloc[-1]
    lv = realized_vol(ranging_ohlcv, settings.RETURNS_STD_PERIOD).iloc[-1]
    assert hv > lv


def test_compute_feature_set_returns_all_fields(trending_ohlcv, settings):
    fs = compute_feature_set(trending_ohlcv, settings)
    assert fs.adx >= 0
    assert fs.atr >= 0
    assert fs.atr_pct >= 0
    assert fs.close > 0
    assert isinstance(fs.as_dict(), dict)
    assert "close" not in fs.as_dict()  # excluded from the feature dict by design


def test_compute_feature_set_raises_on_insufficient_data(settings):
    tiny_df = pd.DataFrame(
        {"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [1, 2]}
    )
    with pytest.raises(ValueError):
        compute_feature_set(tiny_df, settings)


def test_compute_feature_set_raises_on_missing_columns(settings):
    bad_df = pd.DataFrame({"close": list(range(100))})
    with pytest.raises(ValueError):
        compute_feature_set(bad_df, settings)


def test_compute_feature_frame_length_matches_warm_up_window(trending_ohlcv, settings):
    frame = compute_feature_frame(trending_ohlcv, settings)
    assert len(frame) == len(trending_ohlcv) - settings.MIN_BARS_REQUIRED + 1
    assert {"adx", "atr", "atr_pct", "bb_width", "volume_ratio", "trend_slope", "returns_std"}.issubset(
        frame.columns
    )
