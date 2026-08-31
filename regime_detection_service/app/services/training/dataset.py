"""
Builds a labeled training dataset for the ML regime classifier.

Labels are bootstrapped from the rule-based classifier itself (semi-supervised
self-training): we trust the deterministic technical rules as ground truth for the
*structure* axis (TRENDING/RANGING/SIDEWAYS), and train a sklearn classifier on the same
feature vector to learn a smoother, less threshold-brittle decision boundary plus
probability estimates usable as a confidence score. This is a standard, defensible
approach when no hand-labeled regime dataset exists, and it keeps the model consistent
with the rule-based fallback rather than learning something contradictory.

If you later accumulate hand-labeled or outcome-based labels (e.g. derived from realized
forward returns/drawdowns), swap `label_with_rules()` for your own labeling function —
everything downstream (feature matrix, training loop) is unchanged.
"""
from __future__ import annotations

import pandas as pd

from app.config import Settings
from app.core.classifier import FEATURE_ORDER, RuleBasedClassifier
from app.core.features import compute_feature_frame
from app.models.domain import FeatureSet


def label_with_rules(feature_frame: pd.DataFrame) -> pd.Series:
    """Apply the rule-based classifier row-by-row to produce structure-axis labels."""
    rules = RuleBasedClassifier()
    labels = []
    for _, row in feature_frame.iterrows():
        fs = FeatureSet(
            adx=row["adx"],
            atr=row["atr"],
            atr_pct=row["atr_pct"],
            bb_width=row["bb_width"],
            volume_ratio=row["volume_ratio"],
            trend_slope=row["trend_slope"],
            returns_std=row["returns_std"],
            close=row["close"],
        )
        labels.append(rules.classify(fs).regime.value)
    return pd.Series(labels, index=feature_frame.index, name="label")


def build_training_frame(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """
    `df`: raw OHLCV history (ascending by timestamp) for one symbol/timeframe.
    Returns a DataFrame with feature columns (FEATURE_ORDER) + a `label` column, ready
    to hand to `train_classifier.fit()`.
    """
    feature_frame = compute_feature_frame(df, settings)
    feature_frame["label"] = label_with_rules(feature_frame)
    return feature_frame[FEATURE_ORDER + ["label"]].dropna()
