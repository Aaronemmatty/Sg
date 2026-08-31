"""
Domain models for ml_platform_service (8011).

Covers: features, training jobs, model versions, predictions, signals,
        experiment runs, drift monitoring.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class ModelType(StrEnum):
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    LSTM = "lstm"
    TRANSFORMER = "transformer"


class ModelStatus(StrEnum):
    TRAINING = "training"
    TRAINED = "trained"
    VALIDATING = "validating"
    CHAMPION = "champion"
    CHALLENGER = "challenger"
    RETIRED = "retired"
    FAILED = "failed"


class SignalDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class TrainingStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TargetType(StrEnum):
    DIRECTION = "direction"           # BUY / SELL / HOLD classification
    RETURN_5BAR = "return_5bar"       # 5-bar forward return regression
    RETURN_10BAR = "return_10bar"
    VOLATILITY = "volatility"         # next-bar realized vol


# ─────────────────────────────────────────────────────────────────────────────
# Feature vector
# ─────────────────────────────────────────────────────────────────────────────

class FeatureVector(BaseModel):
    """
    Computed feature vector for one symbol at one bar.
    All features are floats; NaN-free (filled or dropped upstream).
    """
    symbol: str
    timestamp: datetime
    # Price-based
    open: float
    high: float
    low: float
    close: float
    volume: float
    # Returns
    ret_1: float = 0.0      # 1-bar log return
    ret_5: float = 0.0
    ret_10: float = 0.0
    ret_20: float = 0.0
    # Moving averages
    sma_5: float = 0.0
    sma_10: float = 0.0
    sma_20: float = 0.0
    sma_50: float = 0.0
    ema_12: float = 0.0
    ema_26: float = 0.0
    # Momentum
    rsi_14: float = 50.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    stoch_k: float = 50.0
    stoch_d: float = 50.0
    # Volatility
    atr_14: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_width: float = 0.0
    bb_pct: float = 0.5
    realized_vol_5: float = 0.0
    realized_vol_20: float = 0.0
    # Volume
    vol_sma_20: float = 0.0
    vol_ratio: float = 1.0    # volume / vol_sma_20
    obv: float = 0.0
    vwap: float = 0.0
    # Price structure
    high_20: float = 0.0
    low_20: float = 0.0
    pct_from_high_20: float = 0.0
    pct_from_low_20: float = 0.0
    # Regime (from regime_detection_service 8005 via Redis)
    regime_trend: float = 0.0     # 0=bear, 0.5=neutral, 1=bull
    regime_vol: float = 0.0       # 0=low, 1=high
    # Time features
    hour: int = 9
    day_of_week: int = 0
    is_monday: int = 0
    is_friday: int = 0

    def to_array(self) -> list[float]:
        """Return ordered float list for model input (excludes metadata fields)."""
        exclude = {"symbol", "timestamp"}
        return [float(v) for k, v in self.model_dump().items() if k not in exclude]

    @property
    def feature_names(self) -> list[str]:
        exclude = {"symbol", "timestamp"}
        return [k for k in self.__class__.model_fields if k not in exclude]


class FeatureBatch(BaseModel):
    """Sequence of FeatureVectors for sequence models (LSTM, Transformer)."""
    symbol: str
    vectors: list[FeatureVector]
    sequence_length: int = Field(default=0)

    def model_post_init(self, __context: Any) -> None:
        self.sequence_length = len(self.vectors)


# ─────────────────────────────────────────────────────────────────────────────
# Training
# ─────────────────────────────────────────────────────────────────────────────

class TrainingConfig(BaseModel):
    """Configuration for one training run."""
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    model_type: ModelType
    symbol: str
    target_type: TargetType = TargetType.DIRECTION
    lookback_bars: int = 500
    sequence_length: int = 20          # for LSTM / Transformer
    n_trials: int = 30                 # Optuna hyperparameter search trials
    early_stopping_rounds: int = 50
    random_seed: int = 42
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TrainingJob(BaseModel):
    """Tracks state of a training job in the DB."""
    job_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    model_type: ModelType
    symbol: str
    target_type: TargetType
    status: TrainingStatus = TrainingStatus.PENDING
    n_samples: int = 0
    train_metric: float | None = None    # accuracy or RMSE depending on target
    val_metric: float | None = None
    test_metric: float | None = None
    best_params: dict[str, Any] = Field(default_factory=dict)
    mlflow_run_id: str | None = None
    model_version_id: uuid.UUID | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_seconds: float | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Model registry
# ─────────────────────────────────────────────────────────────────────────────

class ModelVersion(BaseModel):
    """
    A trained model artifact registered in the model registry.

    Each symbol+model_type pair has at most one CHAMPION at a time.
    A CHALLENGER is the new candidate being evaluated before promotion.
    """
    version_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    model_type: ModelType
    symbol: str
    target_type: TargetType
    status: ModelStatus = ModelStatus.TRAINED
    artifact_path: str = ""              # path to joblib / pt file on disk
    mlflow_run_id: str | None = None
    # Metrics
    train_metric: float | None = None
    val_metric: float | None = None
    test_metric: float | None = None
    directional_accuracy: float | None = None   # % correct direction
    sharpe_on_signals: float | None = None      # backtest Sharpe of model signals
    # Hyperparameters used
    hyperparams: dict[str, Any] = Field(default_factory=dict)
    feature_count: int = 0
    n_samples: int = 0
    training_job_id: uuid.UUID | None = None
    promoted_at: datetime | None = None
    retired_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# Prediction
# ─────────────────────────────────────────────────────────────────────────────

class ModelPrediction(BaseModel):
    """Raw prediction output from one model."""
    prediction_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    model_version_id: uuid.UUID
    model_type: ModelType
    symbol: str
    timestamp: datetime
    direction: SignalDirection
    confidence: float                 # 0.0–1.0
    raw_probabilities: dict[str, float] = Field(default_factory=dict)
    predicted_return: float | None = None   # for regression targets
    predicted_vol: float | None = None
    latency_ms: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EnsemblePrediction(BaseModel):
    """
    Ensemble of predictions from multiple models for one symbol.
    The ensemble signal is what gets published to Redis.
    """
    symbol: str
    timestamp: datetime
    ensemble_direction: SignalDirection
    ensemble_confidence: float
    model_predictions: list[ModelPrediction] = Field(default_factory=list)
    regime_adjusted: bool = False        # True if regime filter was applied
    published_to_redis: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# ML Signal (outbound to Redis)
# ─────────────────────────────────────────────────────────────────────────────

class MLSignal(BaseModel):
    """
    Published to sg:ml:signals:{symbol}.
    Downstream: strategy_service (8004) or execution_orchestrator (8006)
    can subscribe and use as additional signal input.
    """
    signal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    symbol: str
    direction: SignalDirection
    confidence: float
    model_types_used: list[str] = Field(default_factory=list)
    regime_context: str | None = None   # from regime_detection (8005)
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class MLRegimeUpdate(BaseModel):
    """
    Published to sg:ml:regime:{symbol}.
    Enhances regime_detection_service (8005) with ML-derived regime probabilities.
    """
    symbol: str
    bull_probability: float
    bear_probability: float
    neutral_probability: float
    predicted_vol_regime: str     # "low" | "medium" | "high"
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────────────────────
# Experiment tracking
# ─────────────────────────────────────────────────────────────────────────────

class ExperimentRun(BaseModel):
    """Mirrors an MLflow run — stored in sg_db for fast querying."""
    run_id: str                          # MLflow run_id
    experiment_name: str
    model_type: ModelType
    symbol: str
    target_type: TargetType
    params: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)
    status: str = "RUNNING"             # RUNNING | FINISHED | FAILED
    start_time: datetime | None = None
    end_time: datetime | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Monitoring / drift
# ─────────────────────────────────────────────────────────────────────────────

class DriftReport(BaseModel):
    """Population Stability Index (PSI) drift report per feature."""
    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    symbol: str
    model_version_id: uuid.UUID
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    feature_psi: dict[str, float] = Field(default_factory=dict)   # feature → PSI score
    overall_psi: float = 0.0
    drift_detected: bool = False        # True if any feature PSI > 0.2
    n_reference_samples: int = 0
    n_current_samples: int = 0


class PredictionOutcome(BaseModel):
    """
    Ground-truth outcome recorded once the bar closes.
    Used to compute rolling accuracy and trigger retraining.
    """
    outcome_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    prediction_id: uuid.UUID
    symbol: str
    model_type: ModelType
    predicted_direction: SignalDirection
    actual_direction: SignalDirection | None = None
    actual_return: float | None = None
    correct: bool | None = None
    outcome_at: datetime | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
