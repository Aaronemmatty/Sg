"""Unit tests for domain models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.models.domain import (
    EnsemblePrediction,
    FeatureBatch,
    FeatureVector,
    MLSignal,
    ModelPrediction,
    ModelStatus,
    ModelType,
    ModelVersion,
    SignalDirection,
    TargetType,
    TrainingConfig,
    TrainingJob,
    TrainingStatus,
)


def _make_fv(symbol: str = "RELIANCE") -> FeatureVector:
    return FeatureVector(
        symbol=symbol,
        timestamp=datetime.now(timezone.utc),
        open=1000.0, high=1020.0, low=990.0, close=1010.0, volume=500000.0,
    )


class TestFeatureVector:
    def test_to_array_all_float(self):
        fv = _make_fv()
        arr = fv.to_array()
        assert all(isinstance(v, float) for v in arr)

    def test_to_array_length_matches_feature_names(self):
        fv = _make_fv()
        assert len(fv.to_array()) == len(fv.feature_names)

    def test_feature_names_excludes_metadata(self):
        fv = _make_fv()
        assert "symbol" not in fv.feature_names
        assert "timestamp" not in fv.feature_names

    def test_default_rsi_is_50(self):
        fv = _make_fv()
        assert fv.rsi_14 == 50.0

    def test_serialization_round_trip(self):
        fv = _make_fv("INFY")
        json_str = fv.model_dump_json()
        restored = FeatureVector.model_validate_json(json_str)
        assert restored.symbol == "INFY"
        assert restored.close == fv.close


class TestFeatureBatch:
    def test_sequence_length_auto_computed(self):
        vectors = [_make_fv() for _ in range(30)]
        batch = FeatureBatch(symbol="RELIANCE", vectors=vectors)
        assert batch.sequence_length == 30

    def test_empty_batch(self):
        batch = FeatureBatch(symbol="TCS", vectors=[])
        assert batch.sequence_length == 0


class TestModelVersion:
    def test_version_id_auto_generated(self):
        v = ModelVersion(
            model_type=ModelType.XGBOOST,
            symbol="RELIANCE",
            target_type=TargetType.DIRECTION,
        )
        assert v.version_id is not None

    def test_default_status_is_trained(self):
        v = ModelVersion(
            model_type=ModelType.LIGHTGBM,
            symbol="INFY",
            target_type=TargetType.DIRECTION,
        )
        assert v.status == ModelStatus.TRAINED

    def test_json_serialization(self):
        v = ModelVersion(
            model_type=ModelType.LSTM,
            symbol="TCS",
            target_type=TargetType.DIRECTION,
            val_metric=0.62,
            directional_accuracy=0.58,
        )
        data = v.model_dump(mode="json")
        assert data["model_type"] == "lstm"
        assert data["val_metric"] == pytest.approx(0.62)


class TestModelPrediction:
    def test_prediction_id_auto_generated(self):
        pred = ModelPrediction(
            model_version_id=uuid.uuid4(),
            model_type=ModelType.XGBOOST,
            symbol="RELIANCE",
            timestamp=datetime.now(timezone.utc),
            direction=SignalDirection.LONG,
            confidence=0.72,
        )
        assert pred.prediction_id is not None

    def test_default_raw_probabilities_empty(self):
        pred = ModelPrediction(
            model_version_id=uuid.uuid4(),
            model_type=ModelType.LIGHTGBM,
            symbol="INFY",
            timestamp=datetime.now(timezone.utc),
            direction=SignalDirection.FLAT,
            confidence=0.55,
        )
        assert pred.raw_probabilities == {}


class TestEnsemblePrediction:
    def test_model_predictions_default_empty(self):
        ep = EnsemblePrediction(
            symbol="TCS",
            timestamp=datetime.now(timezone.utc),
            ensemble_direction=SignalDirection.LONG,
            ensemble_confidence=0.67,
        )
        assert ep.model_predictions == []
        assert ep.published_to_redis is False

    def test_regime_adjusted_default_false(self):
        ep = EnsemblePrediction(
            symbol="HDFC",
            timestamp=datetime.now(timezone.utc),
            ensemble_direction=SignalDirection.SHORT,
            ensemble_confidence=0.60,
        )
        assert ep.regime_adjusted is False


class TestMLSignal:
    def test_signal_id_auto_generated(self):
        sig = MLSignal(
            symbol="RELIANCE",
            direction=SignalDirection.LONG,
            confidence=0.75,
        )
        assert sig.signal_id is not None

    def test_serialization(self):
        sig = MLSignal(
            symbol="WIPRO",
            direction=SignalDirection.SHORT,
            confidence=0.62,
            model_types_used=["xgboost", "lightgbm"],
        )
        data = sig.model_dump(mode="json")
        assert data["direction"] == "SHORT"
        assert "xgboost" in data["model_types_used"]


class TestTrainingJob:
    def test_default_status_pending(self):
        job = TrainingJob(
            model_type=ModelType.XGBOOST,
            symbol="RELIANCE",
            target_type=TargetType.DIRECTION,
        )
        assert job.status == TrainingStatus.PENDING

    def test_job_id_auto_generated(self):
        job = TrainingJob(
            model_type=ModelType.LIGHTGBM,
            symbol="INFY",
            target_type=TargetType.DIRECTION,
        )
        assert job.job_id is not None
