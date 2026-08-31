"""
Drift Monitor.

Computes Population Stability Index (PSI) per feature to detect
covariate shift between training distribution and current live data.

Also tracks rolling prediction accuracy by comparing predictions to
ground-truth outcomes (recorded once the target bar closes).

Triggers:
  - PSI > 0.2 on any feature → drift_detected flag + Prometheus gauge update
  - Rolling accuracy < 0.48 (below random) → retraining recommendation logged
  - Automatic retraining trigger is a future extension (current: log + metric only)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np

from app.core.logging import get_logger
from app.core.metrics import feature_drift_score, model_accuracy_gauge
from app.db import repository as repo
from app.features.engineer import compute_psi
from app.features.store import get_reference_distribution
from app.models.domain import DriftReport, ModelType, PredictionOutcome, SignalDirection

log = get_logger(__name__)

_PSI_WARN_THRESHOLD = 0.1    # minor drift
_PSI_ALERT_THRESHOLD = 0.2   # significant drift


async def compute_drift_report(
    symbol: str,
    model_type: ModelType,
    current_feature_array: dict[str, list[float]],
) -> DriftReport:
    """
    Compare current feature distribution to training reference.
    Persists the DriftReport to sg_db and updates Prometheus gauges.
    """
    version = await repo.get_champion_model(symbol, model_type)
    if version is None:
        return DriftReport(
            symbol=symbol,
            model_version_id=__import__("uuid").uuid4(),
        )

    reference = await get_reference_distribution(symbol, model_type.value)
    if reference is None:
        log.debug("drift_no_reference_distribution", symbol=symbol, model_type=model_type.value)
        return DriftReport(symbol=symbol, model_version_id=version.version_id)

    feature_psi: dict[str, float] = {}
    drift_detected = False

    for feat_name, ref_vals in reference.items():
        cur_vals = current_feature_array.get(feat_name)
        if cur_vals is None or len(cur_vals) < 10 or len(ref_vals) < 10:
            continue

        psi = compute_psi(np.array(ref_vals), np.array(cur_vals))
        feature_psi[feat_name] = round(psi, 4)

        # Update Prometheus
        feature_drift_score.labels(symbol=symbol, feature=feat_name).set(psi)

        if psi > _PSI_ALERT_THRESHOLD:
            drift_detected = True
            log.warning(
                "feature_drift_significant",
                symbol=symbol,
                feature=feat_name,
                psi=round(psi, 4),
            )
        elif psi > _PSI_WARN_THRESHOLD:
            log.info(
                "feature_drift_minor",
                symbol=symbol,
                feature=feat_name,
                psi=round(psi, 4),
            )

    overall_psi = float(np.mean(list(feature_psi.values()))) if feature_psi else 0.0

    report = DriftReport(
        symbol=symbol,
        model_version_id=version.version_id,
        feature_psi=feature_psi,
        overall_psi=overall_psi,
        drift_detected=drift_detected,
        n_reference_samples=len(next(iter(reference.values()), [])),
        n_current_samples=len(next(iter(current_feature_array.values()), [])),
    )
    await repo.insert_drift_report(report)
    return report


async def record_prediction_outcome(
    prediction_id: __import__("uuid").UUID,
    symbol: str,
    model_type: ModelType,
    actual_return: float,
    outcome_at: datetime | None = None,
) -> PredictionOutcome:
    """
    Record the actual bar outcome for a prior prediction.
    Computes actual direction from return sign and marks prediction correct/incorrect.
    """
    pred = await repo.get_prediction(prediction_id)
    if pred is None:
        raise ValueError(f"Prediction {prediction_id} not found")

    thresh = 0.002
    actual_direction = (
        SignalDirection.LONG if actual_return > thresh
        else SignalDirection.SHORT if actual_return < -thresh
        else SignalDirection.FLAT
    )
    correct = pred.direction == actual_direction

    outcome = PredictionOutcome(
        prediction_id=prediction_id,
        symbol=symbol,
        model_type=model_type,
        predicted_direction=pred.direction,
        actual_direction=actual_direction,
        actual_return=actual_return,
        correct=correct,
        outcome_at=outcome_at or datetime.now(timezone.utc),
    )
    await repo.insert_prediction_outcome(outcome)
    return outcome


async def update_rolling_accuracy(symbol: str, model_type: ModelType, window: int = 50) -> float:
    """
    Compute rolling accuracy over the last `window` predictions with outcomes.
    Updates the Prometheus gauge and returns the accuracy.
    """
    outcomes = await repo.get_recent_outcomes(symbol, model_type, limit=window)
    if not outcomes:
        return 0.0

    correct = sum(1 for o in outcomes if o.get("correct"))
    accuracy = correct / len(outcomes)

    model_accuracy_gauge.labels(model_type=model_type.value, symbol=symbol).set(accuracy)

    if accuracy < 0.48 and len(outcomes) >= window:
        log.warning(
            "model_accuracy_below_threshold",
            symbol=symbol,
            model_type=model_type.value,
            accuracy=round(accuracy, 3),
            n_outcomes=len(outcomes),
        )

    return accuracy
