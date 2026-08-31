"""
Unit tests for training pipeline.

Tests:
  - XGBoost and LightGBM train and predict on synthetic data
  - BaseTrainer dataset splitting is temporal (no leakage)
  - build_sequences produces correct shapes
  - LSTM/Transformer fallback paths work without torch
  - TrainingDispatcher deduplicates concurrent jobs
"""
from __future__ import annotations

import uuid
import numpy as np
import pandas as pd
import pytest

from app.features.store import build_sequences, split_dataset
from app.models.domain import ModelType, TargetType, TrainingConfig


def _synthetic_X_y(n: int = 500, n_features: int = 20, n_classes: int = 3):
    rng = np.random.default_rng(42)
    X = rng.standard_normal((n, n_features)).astype(np.float32)
    y = rng.integers(0, n_classes, n).astype(float)
    return X, y


# ─────────────────────────────────────────────────────────────────────────────
# Dataset utilities
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitDataset:
    def test_sizes_sum_to_total(self):
        X, y = _synthetic_X_y(500)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y, test_split=0.2, val_split=0.1)
        assert len(Xtr) + len(Xv) + len(Xte) == 500

    def test_temporal_order_preserved(self):
        """Train must come before val, val before test — no shuffle."""
        X = np.arange(500).reshape(-1, 1).astype(np.float32)
        y = np.arange(500, dtype=float)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        assert Xtr[-1, 0] < Xv[0, 0]
        assert Xv[-1, 0] < Xte[0, 0]

    def test_test_split_ratio_approximate(self):
        X, y = _synthetic_X_y(1000)
        Xtr, Xv, Xte, *_ = split_dataset(X, y, test_split=0.2, val_split=0.1)
        assert abs(len(Xte) / 1000 - 0.2) < 0.02

    def test_raises_on_too_few_samples(self):
        X, y = _synthetic_X_y(5)
        with pytest.raises(ValueError, match="Too few"):
            split_dataset(X, y)


class TestBuildSequences:
    def test_output_shape(self):
        X, y = _synthetic_X_y(200, n_features=10)
        X_seq, y_seq = build_sequences(X, y, seq_len=20)
        assert X_seq.shape == (180, 20, 10)
        assert len(y_seq) == 180

    def test_raises_on_short_data(self):
        X, y = _synthetic_X_y(10, n_features=5)
        with pytest.raises(ValueError, match="Not enough rows"):
            build_sequences(X, y, seq_len=20)

    def test_y_aligned_to_last_timestep(self):
        """y[i] should correspond to X[i:i+seq_len] last bar."""
        X = np.arange(50).reshape(-1, 1).astype(np.float32)
        y = np.arange(50, dtype=float)
        seq_len = 10
        X_seq, y_seq = build_sequences(X, y, seq_len=seq_len)
        # y_seq[0] should be y[seq_len] = 10
        assert y_seq[0] == pytest.approx(10.0)


# ─────────────────────────────────────────────────────────────────────────────
# XGBoost trainer
# ─────────────────────────────────────────────────────────────────────────────

class TestXGBoostTrainer:
    def _trainer(self):
        from app.training.xgboost_trainer import XGBoostTrainer
        return XGBoostTrainer()

    def test_default_params_keys(self):
        t = self._trainer()
        p = t._default_params()
        assert "n_estimators" in p
        assert "max_depth" in p
        assert "learning_rate" in p

    def test_fit_and_predict_classification(self):
        X, y = _synthetic_X_y(500, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        t = self._trainer()
        params = {**t._default_params(), "n_estimators": 50}
        model = t._fit(Xtr, ytr, Xv, yv, params)
        proba = t._predict_proba(model, Xte)
        assert proba.shape[0] == len(Xte)
        assert proba.shape[1] == 3
        assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-5)

    def test_predict_proba_regression(self):
        """Regression target returns (n, 1) array."""
        rng = np.random.default_rng(0)
        X = rng.standard_normal((400, 15)).astype(np.float32)
        y = rng.standard_normal(400)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        t = self._trainer()
        params = {**t._default_params(), "n_estimators": 30}
        model = t._fit(Xtr, ytr, Xv, yv, params)
        proba = t._predict_proba(model, Xte)
        assert proba.shape == (len(Xte), 1)

    def test_save_and_load(self, tmp_path):
        X, y = _synthetic_X_y(300, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        t = self._trainer()
        params = {**t._default_params(), "n_estimators": 20}
        model = t._fit(Xtr, ytr, Xv, yv, params)
        path = str(tmp_path / "model.pkl")
        t._save_model(model, path)
        loaded = t._load_model(path)
        proba_orig = t._predict_proba(model, Xte)
        proba_load = t._predict_proba(loaded, Xte)
        assert np.allclose(proba_orig, proba_load, atol=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# LightGBM trainer
# ─────────────────────────────────────────────────────────────────────────────

class TestLightGBMTrainer:
    def _trainer(self):
        from app.training.lightgbm_trainer import LightGBMTrainer
        return LightGBMTrainer()

    def test_fit_and_predict(self):
        X, y = _synthetic_X_y(500, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        t = self._trainer()
        params = {**t._default_params(), "n_estimators": 50}
        model = t._fit(Xtr, ytr, Xv, yv, params)
        proba = t._predict_proba(model, Xte)
        assert proba.shape[0] == len(Xte)
        assert proba.shape[1] == 3

    def test_probabilities_sum_to_one(self):
        X, y = _synthetic_X_y(400, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        t = self._trainer()
        params = {**t._default_params(), "n_estimators": 30}
        model = t._fit(Xtr, ytr, Xv, yv, params)
        proba = t._predict_proba(model, Xte)
        assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-5)

    def test_save_and_load(self, tmp_path):
        X, y = _synthetic_X_y(300, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        t = self._trainer()
        params = {**t._default_params(), "n_estimators": 20}
        model = t._fit(Xtr, ytr, Xv, yv, params)
        path = str(tmp_path / "lgbm.pkl")
        t._save_model(model, path)
        loaded = t._load_model(path)
        assert np.allclose(
            t._predict_proba(model, Xte),
            t._predict_proba(loaded, Xte),
            atol=1e-5,
        )


# ─────────────────────────────────────────────────────────────────────────────
# LSTM trainer (sklearn fallback path — torch not installed in test env)
# ─────────────────────────────────────────────────────────────────────────────

class TestLSTMTrainerFallback:
    """
    Tests the sklearn MLP fallback path.
    The torch path is tested separately when torch is available.
    """

    def _trainer(self):
        from app.training.lstm_trainer import LSTMTrainer
        return LSTMTrainer()

    def test_sklearn_fit_returns_model(self):
        t = self._trainer()
        X, y = _synthetic_X_y(400, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        params = t._default_params()
        # Use sklearn path directly
        model = t._sklearn_fit(Xtr, ytr.astype(int), params)
        assert model is not None

    def test_sklearn_predict_proba_shape(self):
        t = self._trainer()
        X, y = _synthetic_X_y(400, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        params = t._default_params()
        model = t._sklearn_fit(Xtr, ytr.astype(int), params)
        proba = model.predict_proba(Xte)
        assert proba.shape[0] == len(Xte)
        assert proba.shape[1] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Transformer trainer (sklearn fallback)
# ─────────────────────────────────────────────────────────────────────────────

class TestTransformerTrainerFallback:
    def _trainer(self):
        from app.training.transformer_trainer import TransformerTrainer
        return TransformerTrainer()

    def test_sklearn_fit_returns_model(self):
        t = self._trainer()
        X, y = _synthetic_X_y(400, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        params = t._default_params()
        model = t._sklearn_fit(Xtr, ytr.astype(int), params)
        assert model is not None

    def test_sklearn_predict_proba(self):
        t = self._trainer()
        X, y = _synthetic_X_y(400, n_classes=3)
        Xtr, Xv, Xte, ytr, yv, yte = split_dataset(X, y)
        params = t._default_params()
        model = t._sklearn_fit(Xtr, ytr.astype(int), params)
        proba = model.predict_proba(Xte)
        assert proba.shape[0] == len(Xte)


# ─────────────────────────────────────────────────────────────────────────────
# Training config model
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingConfig:
    def test_job_id_auto_generated(self):
        config = TrainingConfig(
            model_type=ModelType.XGBOOST,
            symbol="RELIANCE",
            target_type=TargetType.DIRECTION,
        )
        assert config.job_id is not None
        assert isinstance(config.job_id, uuid.UUID)

    def test_defaults_populated(self):
        config = TrainingConfig(
            model_type=ModelType.LIGHTGBM,
            symbol="INFY",
            target_type=TargetType.DIRECTION,
        )
        assert config.n_trials == 30
        assert config.sequence_length == 20
        assert config.random_seed == 42


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher deduplication
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingDispatcher:
    @pytest.mark.asyncio
    async def test_deduplicates_concurrent_jobs(self):
        from unittest.mock import AsyncMock, patch
        from app.training.dispatcher import TrainingDispatcher

        config = TrainingConfig(
            model_type=ModelType.XGBOOST,
            symbol="TESTDEDUP",
            target_type=TargetType.DIRECTION,
        )

        # Patch _run_job to be a long-running coroutine
        async def _fake_run(cfg, key):
            import asyncio
            await asyncio.sleep(10)

        with patch.object(TrainingDispatcher, "_run_job", side_effect=_fake_run):
            r1 = await TrainingDispatcher.submit(config)
            # Submit same symbol+model_type again
            config2 = TrainingConfig(
                model_type=ModelType.XGBOOST,
                symbol="TESTDEDUP",
                target_type=TargetType.DIRECTION,
            )
            r2 = await TrainingDispatcher.submit(config2)

        # First should start, second should be rejected as already running
        assert r1 == "started"
        assert r2 == "already_running"

        # Cleanup
        key = "TESTDEDUP:xgboost"
        task = TrainingDispatcher._active.get(key)
        if task and not task.done():
            task.cancel()
        TrainingDispatcher._active.pop(key, None)
