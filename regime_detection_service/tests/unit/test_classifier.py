from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.classifier import HybridClassifier, MLClassifier, RuleBasedClassifier
from app.core.features import compute_feature_set
from app.models.domain import BreadthSnapshot, RegimeType


def test_rule_based_classifies_trending(trending_ohlcv, settings):
    fs = compute_feature_set(trending_ohlcv, settings)
    result = RuleBasedClassifier().classify(fs)
    assert result.regime == RegimeType.TRENDING
    assert 0.0 <= result.confidence <= 1.0
    assert RegimeType.BULLISH in result.sub_regimes


def test_rule_based_classifies_ranging(ranging_ohlcv, settings):
    fs = compute_feature_set(ranging_ohlcv, settings)
    result = RuleBasedClassifier().classify(fs)
    assert result.regime in (RegimeType.RANGING, RegimeType.SIDEWAYS)


def test_rule_based_classifies_bearish_direction(bearish_ohlcv, settings):
    fs = compute_feature_set(bearish_ohlcv, settings)
    result = RuleBasedClassifier().classify(fs)
    assert RegimeType.BEARISH in result.sub_regimes


def test_rule_based_flags_high_volatility(high_vol_ohlcv, settings):
    fs = compute_feature_set(high_vol_ohlcv, settings)
    result = RuleBasedClassifier().classify(fs)
    assert RegimeType.HIGH_VOLATILITY in result.sub_regimes


def test_rule_based_breadth_sub_regime_extreme(trending_ohlcv, settings):
    fs = compute_feature_set(trending_ohlcv, settings)
    rules = RuleBasedClassifier()
    extreme_breadth = BreadthSnapshot(
        advancing=45, declining=5, unchanged=0, universe_size=50, advance_pct=0.9,
        breadth_regime=RegimeType.RISK_ON, timestamp=datetime.now(timezone.utc),
    )
    sub = rules.breadth_sub_regime(extreme_breadth)
    assert sub == RegimeType.RISK_ON


def test_rule_based_breadth_sub_regime_neutral_is_none(settings):
    rules = RuleBasedClassifier()
    neutral_breadth = BreadthSnapshot(
        advancing=25, declining=25, unchanged=0, universe_size=50, advance_pct=0.5,
        breadth_regime=RegimeType.RISK_ON, timestamp=datetime.now(timezone.utc),
    )
    assert rules.breadth_sub_regime(neutral_breadth) is None


def test_ml_classifier_handles_missing_model_gracefully(tmp_path):
    missing_path = tmp_path / "does_not_exist.joblib"
    ml = MLClassifier(str(missing_path))
    assert ml.is_loaded is False
    assert ml.classify.__self__ is ml  # sanity: bound method exists


def test_ml_classifier_classify_returns_none_when_not_loaded(trending_ohlcv, settings, tmp_path):
    fs = compute_feature_set(trending_ohlcv, settings)
    ml = MLClassifier(str(tmp_path / "missing.joblib"))
    assert ml.classify(fs) is None


def test_hybrid_falls_back_to_rules_without_model(trending_ohlcv, settings, tmp_path):
    fs = compute_feature_set(trending_ohlcv, settings)
    hybrid = HybridClassifier(model_path=str(tmp_path / "missing.joblib"))
    assert hybrid.is_using_ml is False
    result = hybrid.classify(fs)
    assert result.regime == RegimeType.TRENDING
    assert result.model_version == "rule_based_v1"


def test_hybrid_merges_breadth_sub_regime(trending_ohlcv, settings, tmp_path):
    hybrid = HybridClassifier(model_path=str(tmp_path / "missing.joblib"))
    fs = compute_feature_set(trending_ohlcv, settings)
    breadth = BreadthSnapshot(
        advancing=46, declining=4, unchanged=0, universe_size=50, advance_pct=0.92,
        breadth_regime=RegimeType.RISK_ON, timestamp=datetime.now(timezone.utc),
    )
    result = hybrid.classify(fs, breadth=breadth)
    assert RegimeType.RISK_ON in result.sub_regimes


@pytest.fixture
def trained_model_bundle(tmp_path, trending_ohlcv, settings):
    """Train a tiny real model on synthetic data so MLClassifier has something to load."""
    import joblib
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import LabelEncoder

    from app.core.classifier import FEATURE_ORDER
    from app.core.features import compute_feature_frame
    from app.services.training.dataset import label_with_rules

    frame = compute_feature_frame(trending_ohlcv, settings)
    frame["label"] = label_with_rules(frame)
    frame = frame.dropna()

    x = frame[FEATURE_ORDER].values
    y_raw = frame["label"].values
    encoder = LabelEncoder()
    y = encoder.fit_transform(y_raw)

    model = RandomForestClassifier(n_estimators=10, random_state=0)
    model.fit(x, y)

    out_path = tmp_path / "model.joblib"
    joblib.dump({"model": model, "label_encoder": encoder, "version": "test_v1"}, out_path)
    return out_path


def test_ml_classifier_loads_and_predicts(trained_model_bundle, trending_ohlcv, settings):
    fs = compute_feature_set(trending_ohlcv, settings)
    ml = MLClassifier(str(trained_model_bundle))
    assert ml.is_loaded is True
    result = ml.classify(fs)
    assert result is not None
    assert isinstance(result.regime, RegimeType)
    assert 0.0 <= result.confidence <= 1.0


def test_hybrid_uses_ml_when_loaded_and_confident(trained_model_bundle, trending_ohlcv, settings):
    hybrid = HybridClassifier(model_path=str(trained_model_bundle), min_ml_confidence=0.0)
    assert hybrid.is_using_ml is True
    fs = compute_feature_set(trending_ohlcv, settings)
    result = hybrid.classify(fs)
    assert result.model_version == "test_v1"
