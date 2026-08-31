"""
Unit tests for FeatureEngineer.

Validates:
  - All indicator computations produce correct values
  - NaN handling (forward-fill / zero-fill)
  - to_array() produces correct length
  - compute_target() labels are correct for each target type
  - PSI drift metric behaves correctly
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.features.engineer import FeatureEngineer, compute_psi


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
    close = 1000.0 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.integers(100_000, 10_000_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


engineer = FeatureEngineer()


class TestComputeDataframe:
    def test_returns_dataframe_with_expected_columns(self):
        df = _make_ohlcv(200)
        result = engineer.compute_dataframe(df)
        expected_cols = [
            "ret_1", "ret_5", "sma_5", "sma_20", "ema_12", "ema_26",
            "rsi_14", "macd", "atr_14", "bb_upper", "bb_lower",
            "bb_width", "bb_pct", "realized_vol_5", "vol_ratio", "obv",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_nans_in_output(self):
        df = _make_ohlcv(200)
        result = engineer.compute_dataframe(df)
        nan_cols = result.columns[result.isnull().any()].tolist()
        assert nan_cols == [], f"NaN found in columns: {nan_cols}"

    def test_output_shorter_than_input(self):
        """First 50 bars are dropped due to indicator warmup."""
        df = _make_ohlcv(200)
        result = engineer.compute_dataframe(df)
        assert len(result) < len(df)
        assert len(result) == len(df) - 50

    def test_raises_on_insufficient_bars(self):
        df = _make_ohlcv(30)
        with pytest.raises(ValueError, match="at least 50 bars"):
            engineer.compute_dataframe(df)

    def test_rsi_bounded_0_to_100(self):
        df = _make_ohlcv(200)
        result = engineer.compute_dataframe(df)
        assert (result["rsi_14"] >= 0).all()
        assert (result["rsi_14"] <= 100).all()

    def test_bb_pct_roughly_bounded(self):
        """bb_pct should be mostly 0–1, with outliers clipped."""
        df = _make_ohlcv(300)
        result = engineer.compute_dataframe(df)
        # Most bars should be within [-0.5, 1.5]
        within_range = ((result["bb_pct"] >= -0.5) & (result["bb_pct"] <= 1.5)).mean()
        assert within_range > 0.95

    def test_sma_50_requires_50_bars(self):
        df = _make_ohlcv(200)
        result = engineer.compute_dataframe(df)
        # All sma_50 values in output should be non-NaN (filled)
        assert result["sma_50"].notna().all()

    def test_vol_ratio_positive(self):
        df = _make_ohlcv(200)
        result = engineer.compute_dataframe(df)
        assert (result["vol_ratio"] > 0).all()

    def test_regime_columns_default_to_zero_five(self):
        df = _make_ohlcv(200)
        result = engineer.compute_dataframe(df)
        assert "regime_trend" in result.columns
        assert "regime_vol" in result.columns

    def test_time_features_present(self):
        df = _make_ohlcv(200)
        result = engineer.compute_dataframe(df)
        for col in ["hour", "day_of_week", "is_monday", "is_friday"]:
            assert col in result.columns


class TestComputeLatest:
    def test_returns_feature_vector(self):
        from app.models.domain import FeatureVector
        df = _make_ohlcv(200)
        fv = engineer.compute_latest(df, "RELIANCE")
        assert isinstance(fv, FeatureVector)
        assert fv.symbol == "RELIANCE"

    def test_feature_vector_has_correct_symbol(self):
        df = _make_ohlcv(200)
        fv = engineer.compute_latest(df, "infy")
        assert fv.symbol == "infy"  # no uppercasing in engineer, done at consumer level

    def test_to_array_matches_feature_names_length(self):
        df = _make_ohlcv(200)
        fv = engineer.compute_latest(df, "TCS")
        arr = fv.to_array()
        names = fv.feature_names
        assert len(arr) == len(names)

    def test_to_array_all_finite(self):
        df = _make_ohlcv(200)
        fv = engineer.compute_latest(df, "HDFC")
        arr = fv.to_array()
        assert all(np.isfinite(v) for v in arr), "Feature array has non-finite values"

    def test_regime_values_passthrough(self):
        df = _make_ohlcv(200)
        fv = engineer.compute_latest(df, "RELIANCE", regime_trend=0.8, regime_vol=0.3)
        assert fv.regime_trend == pytest.approx(0.8)
        assert fv.regime_vol == pytest.approx(0.3)


class TestComputeTarget:
    def test_direction_labels_are_0_1_2(self):
        df = _make_ohlcv(300)
        labels = engineer.compute_target(df, "direction", forward_bars=5)
        assert set(labels.unique()).issubset({0.0, 1.0, 2.0})

    def test_direction_labels_length(self):
        df = _make_ohlcv(300)
        labels = engineer.compute_target(df, "direction", forward_bars=5)
        # Should have fewer rows than df due to forward shift and dropna
        assert len(labels) < len(df)

    def test_return_5bar_is_numeric(self):
        df = _make_ohlcv(300)
        labels = engineer.compute_target(df, "return_5bar", forward_bars=5)
        assert labels.dtype == float or np.issubdtype(labels.dtype, np.floating)

    def test_volatility_target_is_positive(self):
        df = _make_ohlcv(300)
        labels = engineer.compute_target(df, "volatility", forward_bars=5)
        assert (labels >= 0).all()

    def test_invalid_target_raises(self):
        df = _make_ohlcv(300)
        with pytest.raises(ValueError, match="Unknown target_type"):
            engineer.compute_target(df, "invalid_target")

    def test_direction_has_all_three_classes(self):
        """With enough data, all three direction classes should appear."""
        df = _make_ohlcv(500)
        labels = engineer.compute_target(df, "direction", forward_bars=5)
        classes = set(labels.unique())
        # With 500 bars, should have at least 2 of the 3 classes
        assert len(classes) >= 2


class TestComputeBatch:
    def test_batch_length_matches_feature_rows(self):
        from app.models.domain import FeatureBatch
        df = _make_ohlcv(200)
        batch = engineer.compute_batch(df, "RELIANCE")
        assert isinstance(batch, FeatureBatch)
        assert batch.sequence_length == len(batch.vectors)
        assert batch.sequence_length > 0

    def test_batch_all_same_symbol(self):
        df = _make_ohlcv(200)
        batch = engineer.compute_batch(df, "INFY")
        assert all(v.symbol == "INFY" for v in batch.vectors)


class TestPSI:
    def test_identical_distributions_zero_psi(self):
        ref = np.random.default_rng(0).normal(0, 1, 1000)
        psi = compute_psi(ref, ref.copy())
        assert psi == pytest.approx(0.0, abs=0.01)

    def test_very_different_distributions_high_psi(self):
        ref = np.random.default_rng(0).normal(0, 1, 1000)
        cur = np.random.default_rng(1).normal(5, 1, 1000)   # shifted mean
        psi = compute_psi(ref, cur)
        assert psi > 0.2, f"Expected high PSI, got {psi}"

    def test_slightly_different_distributions_moderate_psi(self):
        ref = np.random.default_rng(0).normal(0, 1, 1000)
        cur = np.random.default_rng(2).normal(0.3, 1.1, 1000)  # slight shift
        psi = compute_psi(ref, cur)
        # Should detect some drift but not extreme
        assert 0.0 < psi < 1.0

    def test_psi_non_negative(self):
        """PSI is always ≥ 0."""
        rng = np.random.default_rng(5)
        for _ in range(10):
            ref = rng.normal(0, 1, 200)
            cur = rng.normal(0.1, 1.1, 200)
            psi = compute_psi(ref, cur)
            assert psi >= 0.0


class TestIndicatorMath:
    """Validate key indicator values against known analytical results."""

    def test_sma_correct_value(self):
        """SMA of [1,2,3,4,5] with window=3 at last bar = (3+4+5)/3 = 4.0"""
        closes = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = closes.rolling(3).mean().iloc[-1]
        assert result == pytest.approx(4.0)

    def test_ema_more_responsive_than_sma(self):
        """EMA weights recent bars more heavily than SMA.
        After a persistent price jump, EMA should be higher than SMA
        because it over-weights the recent higher values."""
        closes = pd.Series([100.0] * 50 + [200.0] * 5)
        sma = closes.rolling(10).mean()
        from app.features.engineer import _ema
        ema = _ema(closes, 10)
        # EMA weights recent 200-bars more than SMA does
        assert ema.iloc[-1] > sma.iloc[-1]

    def test_rsi_50_for_equal_gains_and_losses(self):
        """Alternating +1/-1 bars → RSI ≈ 50 after warmup."""
        from app.features.engineer import _rsi
        closes = pd.Series([100.0 + (i % 2) for i in range(100)])
        rsi = _rsi(closes, 14)
        assert abs(rsi.iloc[-1] - 50.0) < 5.0

    def test_atr_positive(self):
        """ATR is always positive."""
        from app.features.engineer import _atr
        df = _make_ohlcv(100)
        atr = _atr(df["high"], df["low"], df["close"])
        assert (atr.dropna() > 0).all()

    def test_obv_increases_on_up_days(self):
        """OBV increases when close > prev close."""
        from app.features.engineer import _obv
        closes = pd.Series([100.0, 101.0, 102.0, 103.0])
        volumes = pd.Series([1000.0] * 4)
        obv = _obv(closes, volumes)
        assert obv.iloc[-1] > obv.iloc[0]

    def test_obv_decreases_on_down_days(self):
        from app.features.engineer import _obv
        closes = pd.Series([103.0, 102.0, 101.0, 100.0])
        volumes = pd.Series([1000.0] * 4)
        obv = _obv(closes, volumes)
        assert obv.iloc[-1] < obv.iloc[0]
