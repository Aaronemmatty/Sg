"""Prometheus metrics for ml_platform_service (8011)."""
from prometheus_client import Counter, Gauge, Histogram

# ── Feature computation ───────────────────────────────────────────────────────
feature_computation_total = Counter(
    "ml_feature_computation_total", "Feature vectors computed", ["symbol"]
)
feature_computation_errors = Counter(
    "ml_feature_computation_errors_total", "Feature computation failures", ["symbol"]
)
feature_computation_latency = Histogram(
    "ml_feature_computation_latency_seconds", "Time to compute feature vector",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5),
)

# ── Training ─────────────────────────────────────────────────────────────────
training_runs_total = Counter(
    "ml_training_runs_total", "Model training jobs started", ["model_type", "symbol"]
)
training_success_total = Counter(
    "ml_training_success_total", "Successful training completions", ["model_type", "symbol"]
)
training_errors_total = Counter(
    "ml_training_errors_total", "Training failures", ["model_type", "symbol"]
)
training_duration_seconds = Histogram(
    "ml_training_duration_seconds", "End-to-end training time",
    ["model_type"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600),
)

# ── Prediction serving ────────────────────────────────────────────────────────
predictions_total = Counter(
    "ml_predictions_total", "Prediction requests served", ["model_type", "symbol"]
)
prediction_latency_seconds = Histogram(
    "ml_prediction_latency_seconds", "Time to generate one prediction",
    ["model_type"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)
prediction_cache_hits = Counter(
    "ml_prediction_cache_hits_total", "Predictions served from cache", ["symbol"]
)
prediction_confidence = Histogram(
    "ml_prediction_confidence", "Model prediction confidence scores",
    ["model_type"],
    buckets=(0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0),
)
signals_published_total = Counter(
    "ml_signals_published_total", "ML signals published to Redis", ["symbol", "direction"]
)

# ── Model registry ────────────────────────────────────────────────────────────
champion_models_active = Gauge(
    "ml_champion_models_active", "Number of active champion models"
)
model_promotions_total = Counter(
    "ml_model_promotions_total", "Challenger → champion promotions", ["model_type"]
)

# ── Monitoring / drift ────────────────────────────────────────────────────────
feature_drift_score = Gauge(
    "ml_feature_drift_score", "PSI drift score vs training distribution",
    ["symbol", "feature"],
)
model_accuracy_gauge = Gauge(
    "ml_model_accuracy", "Rolling directional accuracy (last 50 predictions)",
    ["model_type", "symbol"],
)
