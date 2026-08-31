"""
Classification layer: turns a FeatureSet into a (RegimeType, confidence, sub_regimes) tuple.

Three implementations:
  - RuleBasedClassifier: pure technical thresholds. Always available, zero dependencies
    beyond the feature values themselves. Used standalone when no trained model is present,
    and as the fallback/overlay inside HybridClassifier.
  - MLClassifier: thin wrapper around a persisted sklearn RandomForest/GradientBoosting
    model (joblib). Predicts the *structure* axis (TRENDING/RANGING/SIDEWAYS) primarily;
    direction/volatility/breadth sub-regimes are still derived from rules, since those are
    well-defined thresholds rather than something worth spending model capacity on.
  - HybridClassifier: tries MLClassifier, falls back to RuleBasedClassifier transparently
    if no model is loaded or prediction fails. This is what the engine talks to.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

from app.models.domain import (
    BreadthSnapshot,
    FeatureSet,
    RegimeType,
)

logger = logging.getLogger(__name__)

FEATURE_ORDER = ["adx", "atr_pct", "bb_width", "volume_ratio", "trend_slope", "returns_std"]


class ClassificationResult:
    __slots__ = ("regime", "confidence", "sub_regimes", "model_version")

    def __init__(
        self,
        regime: RegimeType,
        confidence: float,
        sub_regimes: list[RegimeType],
        model_version: Optional[str] = None,
    ):
        self.regime = regime
        self.confidence = confidence
        self.sub_regimes = sub_regimes
        self.model_version = model_version


class RuleBasedClassifier:
    """
    Pure technical-threshold classifier. Deterministic, explainable, no training required.

    Structure axis (primary `regime`):
      ADX >= adx_trend_threshold                -> TRENDING
      bb_width <= bb_width_ranging_threshold     -> RANGING
      otherwise                                  -> SIDEWAYS

    Volatility axis (sub-regime):
      atr_pct >= high_vol_threshold  -> HIGH_VOLATILITY
      atr_pct <= low_vol_threshold   -> LOW_VOLATILITY

    Direction axis (sub-regime):
      trend_slope >= 0   -> BULLISH
      trend_slope < 0    -> BEARISH
    """

    def __init__(
        self,
        adx_trend_threshold: float = 25.0,
        adx_strong_trend_threshold: float = 35.0,
        bb_width_ranging_threshold: float = 0.03,
        high_vol_atr_pct_threshold: float = 0.012,
        low_vol_atr_pct_threshold: float = 0.004,
        slope_flat_threshold: float = 0.0005,
    ):
        self.adx_trend_threshold = adx_trend_threshold
        self.adx_strong_trend_threshold = adx_strong_trend_threshold
        self.bb_width_ranging_threshold = bb_width_ranging_threshold
        self.high_vol_atr_pct_threshold = high_vol_atr_pct_threshold
        self.low_vol_atr_pct_threshold = low_vol_atr_pct_threshold
        self.slope_flat_threshold = slope_flat_threshold

    def classify(self, features: FeatureSet) -> ClassificationResult:
        sub_regimes: list[RegimeType] = []

        # --- Structure axis -------------------------------------------------
        if features.adx >= self.adx_trend_threshold:
            structure = RegimeType.TRENDING
            structure_conf = min(1.0, 0.5 + (features.adx - self.adx_trend_threshold) / 40.0)
        elif features.bb_width <= self.bb_width_ranging_threshold:
            structure = RegimeType.RANGING
            structure_conf = min(
                1.0, 0.5 + (self.bb_width_ranging_threshold - features.bb_width) / 0.03
            )
        else:
            structure = RegimeType.SIDEWAYS
            # Confidence highest when ADX is far below trend threshold and BB width is
            # mid-range (i.e. clearly neither trending nor compressed).
            structure_conf = 0.55

        # --- Volatility axis (sub-regime) -----------------------------------
        if features.atr_pct >= self.high_vol_atr_pct_threshold:
            sub_regimes.append(RegimeType.HIGH_VOLATILITY)
        elif features.atr_pct <= self.low_vol_atr_pct_threshold:
            sub_regimes.append(RegimeType.LOW_VOLATILITY)

        # --- Direction axis (sub-regime) -------------------------------------
        if abs(features.trend_slope) >= self.slope_flat_threshold:
            sub_regimes.append(RegimeType.BULLISH if features.trend_slope > 0 else RegimeType.BEARISH)

        return ClassificationResult(
            regime=structure,
            confidence=round(float(structure_conf), 4),
            sub_regimes=sub_regimes,
            model_version="rule_based_v1",
        )

    def breadth_sub_regime(self, breadth: Optional[BreadthSnapshot]) -> Optional[RegimeType]:
        if breadth is None:
            return None
        from app.core.breadth import BreadthCalculator

        if BreadthCalculator().is_extreme(breadth):
            return breadth.breadth_regime
        return None


class MLClassifier:
    """Wraps a persisted sklearn classifier (RandomForest or GradientBoosting)."""

    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self.model = None
        self.label_encoder = None
        self.model_version: Optional[str] = None
        self._try_load()

    def _try_load(self) -> None:
        if not self.model_path.exists():
            logger.warning("regime ML model not found at %s — running rule-based only", self.model_path)
            return
        try:
            import joblib

            bundle = joblib.load(self.model_path)
            self.model = bundle["model"]
            self.label_encoder = bundle["label_encoder"]
            self.model_version = bundle.get("version", "unknown")
            logger.info("loaded regime ML model version=%s from %s", self.model_version, self.model_path)
        except Exception:  # noqa: BLE001 - any load failure must not crash the service
            logger.exception("failed to load regime ML model — falling back to rule-based")
            self.model = None

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def classify(self, features: FeatureSet) -> Optional[ClassificationResult]:
        if not self.is_loaded:
            return None
        try:
            x = np.array([[getattr(features, f) for f in FEATURE_ORDER]])
            proba = self.model.predict_proba(x)[0]
            pred_idx = int(np.argmax(proba))
            label = self.label_encoder.inverse_transform([pred_idx])[0]
            confidence = float(proba[pred_idx])
            regime = RegimeType(label)
            return ClassificationResult(
                regime=regime, confidence=round(confidence, 4), sub_regimes=[], model_version=self.model_version
            )
        except Exception:  # noqa: BLE001
            logger.exception("ML classification failed — caller should fall back to rule-based")
            return None


class HybridClassifier:
    """
    Tries the ML model first; falls back to the rule-based classifier whenever the model
    is missing, fails, or returns a low-confidence prediction. Sub-regimes (volatility,
    direction) always come from the rule overlay regardless of which classifier produced
    the primary `regime`, since those axes are well-defined thresholds, not learned classes.
    """

    def __init__(self, model_path: str, min_ml_confidence: float = 0.45):
        self.ml = MLClassifier(model_path)
        self.rules = RuleBasedClassifier()
        self.min_ml_confidence = min_ml_confidence

    @property
    def is_using_ml(self) -> bool:
        return self.ml.is_loaded

    def classify(
        self, features: FeatureSet, breadth: Optional[BreadthSnapshot] = None
    ) -> ClassificationResult:
        rule_result = self.rules.classify(features)

        ml_result = self.ml.classify(features) if self.ml.is_loaded else None
        if ml_result is not None and ml_result.confidence >= self.min_ml_confidence:
            primary_regime = ml_result.regime
            confidence = ml_result.confidence
            model_version = ml_result.model_version
        else:
            primary_regime = rule_result.regime
            confidence = rule_result.confidence
            model_version = rule_result.model_version

        sub_regimes = list(rule_result.sub_regimes)
        breadth_sub = self.rules.breadth_sub_regime(breadth)
        if breadth_sub is not None and breadth_sub not in sub_regimes:
            sub_regimes.append(breadth_sub)

        return ClassificationResult(
            regime=primary_regime,
            confidence=confidence,
            sub_regimes=sub_regimes,
            model_version=model_version,
        )
