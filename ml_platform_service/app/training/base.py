"""
Abstract base trainer — all four model trainers inherit from this.

Lifecycle:
  1. load_data()       — fetch features from feature store
  2. preprocess()      — scale, build sequences if needed
  3. tune()            — Optuna hyperparameter search
  4. train()           — fit best params on train+val
  5. evaluate()        — compute test metrics
  6. save_artifact()   — joblib / torch serialize to disk
  7. log_experiment()  — MLflow run (params, metrics, artifact path)
  8. register()        — write ModelVersion to DB, auto-promote if better

Subclasses must implement: _default_params(), _objective(), _fit(), _predict_proba()
"""
from __future__ import annotations

import abc
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import (
    training_duration_seconds,
    training_errors_total,
    training_runs_total,
    training_success_total,
)
from app.db import repository as repo
from app.features.engineer import FeatureEngineer
from app.features.store import (
    build_sequences,
    cache_reference_distribution,
    get_feature_count,
    get_training_dataset,
    split_dataset,
)
from app.models.domain import (
    ModelStatus,
    ModelType,
    ModelVersion,
    TargetType,
    TrainingConfig,
    TrainingJob,
    TrainingStatus,
)

log = get_logger(__name__)

_engineer = FeatureEngineer()


class BaseTrainer(abc.ABC):
    """
    Abstract trainer. Each subclass wraps one model family.

    Subclasses must implement:
      _default_params()     → dict of default hyperparameters
      _objective(trial, X_tr, y_tr, X_val, y_val) → float metric (higher=better)
      _fit(X_tr, y_tr, X_val, y_val, params)      → fitted model object
      _predict_proba(model, X)                     → np.ndarray shape (n, n_classes)
      _save_model(model, path)
      _load_model(path)
    """

    model_type: ModelType  # set by subclass

    # ── Public entry point ────────────────────────────────────────────────────

    async def run(self, config: TrainingConfig) -> TrainingJob:
        """Execute the full training pipeline. Returns final TrainingJob state."""
        job = TrainingJob(
            job_id=config.job_id,
            model_type=config.model_type,
            symbol=config.symbol,
            target_type=config.target_type,
            status=TrainingStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        await repo.upsert_training_job(job)
        training_runs_total.labels(
            model_type=config.model_type.value, symbol=config.symbol
        ).inc()

        t0 = time.perf_counter()
        try:
            job = await self._pipeline(job, config)
            job.status = TrainingStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job.duration_seconds = time.perf_counter() - t0
            training_success_total.labels(
                model_type=config.model_type.value, symbol=config.symbol
            ).inc()
            training_duration_seconds.labels(
                model_type=config.model_type.value
            ).observe(job.duration_seconds)
            log.info(
                "training_completed",
                job_id=str(job.job_id),
                model_type=config.model_type.value,
                symbol=config.symbol,
                val_metric=job.val_metric,
                duration_s=round(job.duration_seconds, 1),
            )
        except Exception as exc:
            job.status = TrainingStatus.FAILED
            job.error_message = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            job.duration_seconds = time.perf_counter() - t0
            training_errors_total.labels(
                model_type=config.model_type.value, symbol=config.symbol
            ).inc()
            log.exception(
                "training_failed",
                job_id=str(job.job_id),
                model_type=config.model_type.value,
                symbol=config.symbol,
            )
        finally:
            await repo.upsert_training_job(job)

        return job

    # ── Pipeline stages ───────────────────────────────────────────────────────

    async def _pipeline(self, job: TrainingJob, config: TrainingConfig) -> TrainingJob:
        # 1. Data
        n_available = await get_feature_count(config.symbol)
        if n_available < settings.train_min_samples:
            raise ValueError(
                f"Insufficient data: {n_available} < {settings.train_min_samples} samples"
            )

        feat_df = await get_training_dataset(config.symbol, limit=10_000)
        if feat_df.empty:
            raise ValueError("No feature data returned from feature store")

        job.n_samples = len(feat_df)

        # 2. Targets
        # Reconstruct raw OHLCV subset from stored features for target computation
        ohlcv_cols = ["open", "high", "low", "close", "volume"]
        missing = [c for c in ohlcv_cols if c not in feat_df.columns]
        if missing:
            raise ValueError(f"Feature store missing OHLCV columns: {missing}")

        targets = _engineer.compute_target(feat_df, config.target_type.value)
        # Align features to targets (target has fewer rows due to forward shift)
        feat_df = feat_df.loc[targets.index]
        X_raw = feat_df.drop(columns=ohlcv_cols, errors="ignore").values.astype(np.float32)
        y_raw = targets.values

        # 3. Scaling (StandardScaler on train split — fit on train, apply to all)
        from sklearn.preprocessing import StandardScaler, LabelEncoder
        is_classification = config.target_type == TargetType.DIRECTION

        n = len(X_raw)
        test_n = max(1, int(n * settings.train_test_split))
        val_n = max(1, int(n * settings.train_validation_split))
        train_n = n - val_n - test_n

        scaler = StandardScaler()
        X_scaled = X_raw.copy()
        X_scaled[:train_n] = scaler.fit_transform(X_raw[:train_n])
        X_scaled[train_n:train_n + val_n] = scaler.transform(X_raw[train_n:train_n + val_n])
        X_scaled[train_n + val_n:] = scaler.transform(X_raw[train_n + val_n:])

        # 4. Sequence building for LSTM/Transformer
        use_sequences = self.model_type in (ModelType.LSTM, ModelType.TRANSFORMER)
        if use_sequences:
            X_scaled, y_raw = build_sequences(X_scaled, y_raw, config.sequence_length)

        X_train, X_val, X_test, y_train, y_val, y_test = split_dataset(
            X_scaled, y_raw,
            test_split=settings.train_test_split,
            val_split=settings.train_validation_split,
        )

        # 5. Optuna hyperparameter search
        best_params = await self._run_optuna(
            config, X_train, y_train, X_val, y_val
        )
        job.best_params = best_params

        # 6. Final fit on train + val combined
        X_trainval = np.vstack([X_train, X_val])
        y_trainval = np.concatenate([y_train, y_val])
        model = self._fit(X_trainval, y_trainval, X_val, y_val, best_params)

        # 7. Evaluate
        train_metric, val_metric, test_metric, dir_acc = self._evaluate(
            model, X_train, y_train, X_val, y_val, X_test, y_test,
            is_classification=is_classification,
        )
        job.train_metric = train_metric
        job.val_metric = val_metric
        job.test_metric = test_metric

        # 8. Cache reference distribution for drift monitoring
        feature_names = [c for c in feat_df.columns if c not in ohlcv_cols]
        ref_dist = {
            name: X_train[:, i].tolist()
            for i, name in enumerate(feature_names[:X_train.shape[1]])
        }
        await cache_reference_distribution(config.symbol, config.model_type.value, ref_dist)

        # 9. Save artifact
        artifact_path = self._artifact_path(config)
        Path(artifact_path).parent.mkdir(parents=True, exist_ok=True)
        self._save_model(model, artifact_path)

        # 10. MLflow experiment log
        mlflow_run_id = await self._log_mlflow(
            config, best_params,
            {"train": train_metric, "val": val_metric, "test": test_metric,
             "directional_accuracy": dir_acc},
            artifact_path,
        )
        job.mlflow_run_id = mlflow_run_id

        # 11. Register model version
        version = ModelVersion(
            model_type=config.model_type,
            symbol=config.symbol,
            target_type=config.target_type,
            status=ModelStatus.TRAINED,
            artifact_path=artifact_path,
            mlflow_run_id=mlflow_run_id,
            train_metric=train_metric,
            val_metric=val_metric,
            test_metric=test_metric,
            directional_accuracy=dir_acc,
            hyperparams=best_params,
            feature_count=X_train.shape[-1],
            n_samples=job.n_samples,
            training_job_id=job.job_id,
        )
        version = await repo.register_model_version(version)
        job.model_version_id = version.version_id

        # 12. Auto-promote if better than current champion
        if settings.model_champion_auto_promote:
            await self._maybe_promote(version)

        return job

    async def _run_optuna(
        self,
        config: TrainingConfig,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> dict[str, Any]:
        """Run Optuna hyperparameter search. Returns best params dict."""
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial) -> float:
            try:
                return self._objective(trial, X_train, y_train, X_val, y_val)
            except Exception:
                return 0.0

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=config.random_seed),
        )
        # Use config hyperparams as starting point if provided
        if config.hyperparams:
            study.enqueue_trial(config.hyperparams)

        n_trials = min(config.n_trials, 20)  # cap for responsiveness
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

        best = study.best_params
        log.info(
            "optuna_search_complete",
            model_type=config.model_type.value,
            symbol=config.symbol,
            n_trials=n_trials,
            best_value=study.best_value,
        )
        return {**self._default_params(), **best}

    def _evaluate(
        self, model: Any,
        X_train, y_train, X_val, y_val, X_test, y_test,
        is_classification: bool,
    ) -> tuple[float, float, float, float]:
        """Return (train_metric, val_metric, test_metric, directional_accuracy)."""
        from sklearn.metrics import accuracy_score, mean_squared_error

        def score(X, y):
            if is_classification:
                preds = np.argmax(self._predict_proba(model, X), axis=1)
                return float(accuracy_score(y.astype(int), preds.astype(int)))
            else:
                preds = self._predict_proba(model, X)[:, 0]
                mse = mean_squared_error(y, preds)
                return float(1.0 / (1.0 + mse))  # normalize to 0-1

        train_m = score(X_train, y_train)
        val_m = score(X_val, y_val)
        test_m = score(X_test, y_test)

        # Directional accuracy: fraction of correct up/down predictions
        if not is_classification:
            proba = self._predict_proba(model, X_test)
            dir_pred = np.argmax(proba, axis=1) if proba.shape[1] > 1 else (proba[:, 0] > 0).astype(int)
            dir_actual = (y_test > 0).astype(int)
            dir_acc = float(accuracy_score(dir_actual, dir_pred))
        else:
            proba = self._predict_proba(model, X_test)
            preds = np.argmax(proba, axis=1)
            dir_pred = (preds == 2).astype(int)  # class 2 = UP
            dir_actual = (y_test == 2).astype(int)
            dir_acc = float(accuracy_score(dir_actual, dir_pred))

        return train_m, val_m, test_m, dir_acc

    async def _maybe_promote(self, challenger: ModelVersion) -> None:
        """Auto-promote challenger to champion if it beats the current champion."""
        champion = await repo.get_champion_model(challenger.symbol, challenger.model_type)
        if champion is None:
            await repo.promote_model(challenger.version_id)
            log.info(
                "model_promoted_first",
                version_id=str(challenger.version_id),
                model_type=challenger.model_type.value,
                symbol=challenger.symbol,
            )
            return

        champ_metric = champion.val_metric or 0.0
        chall_metric = challenger.val_metric or 0.0
        if chall_metric > champ_metric * 1.005:  # 0.5% improvement threshold
            await repo.retire_model(champion.version_id)
            await repo.promote_model(challenger.version_id)
            log.info(
                "model_promoted",
                old_version=str(champion.version_id),
                new_version=str(challenger.version_id),
                model_type=challenger.model_type.value,
                symbol=challenger.symbol,
                old_metric=champ_metric,
                new_metric=chall_metric,
            )

    async def _log_mlflow(
        self,
        config: TrainingConfig,
        params: dict,
        metrics: dict,
        artifact_path: str,
    ) -> str | None:
        """Log to MLflow. Returns run_id or None on failure."""
        try:
            import mlflow
            mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
            mlflow.set_experiment(settings.mlflow_experiment_name)

            with mlflow.start_run() as run:
                mlflow.set_tags({
                    "model_type": config.model_type.value,
                    "symbol": config.symbol,
                    "target_type": config.target_type.value,
                })
                mlflow.log_params({k: str(v) for k, v in params.items()})
                mlflow.log_metrics({k: float(v) for k, v in metrics.items() if v is not None})
                mlflow.log_artifact(artifact_path)
                return run.info.run_id
        except Exception:
            log.warning("mlflow_log_failed", job_id=str(config.job_id))
            return None

    def _artifact_path(self, config: TrainingConfig) -> str:
        return (
            f"{settings.model_artifacts_path}"
            f"/{config.symbol}/{config.model_type.value}"
            f"/{config.job_id}.pkl"
        )

    # ── Abstract interface ────────────────────────────────────────────────────

    @abc.abstractmethod
    def _default_params(self) -> dict[str, Any]: ...

    @abc.abstractmethod
    def _objective(
        self, trial: Any,
        X_train: np.ndarray, y_train: np.ndarray,
        X_val: np.ndarray, y_val: np.ndarray,
    ) -> float: ...

    @abc.abstractmethod
    def _fit(
        self,
        X_train: np.ndarray, y_train: np.ndarray,
        X_val: np.ndarray, y_val: np.ndarray,
        params: dict[str, Any],
    ) -> Any: ...

    @abc.abstractmethod
    def _predict_proba(self, model: Any, X: np.ndarray) -> np.ndarray: ...

    @abc.abstractmethod
    def _save_model(self, model: Any, path: str) -> None: ...

    @abc.abstractmethod
    def _load_model(self, path: str) -> Any: ...
