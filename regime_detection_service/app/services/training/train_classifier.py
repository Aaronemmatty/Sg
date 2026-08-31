"""
Offline training CLI for the hybrid regime classifier's ML component.

Usage:
    python -m app.services.training.train_classifier \\
        --symbol NIFTY50 --timeframe 5m --lookback-days 730 \\
        --out models/regime_classifier.joblib

Pulls historical bars from the database (via the same `market_data_client` the live
service uses), builds a rule-bootstrapped labeled dataset, trains a RandomForest or
GradientBoosting classifier, and persists it with joblib alongside metadata (version,
feature order, label classes) so `app/core/classifier.py::MLClassifier` can load it.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

from app.config import get_settings
from app.core.classifier import FEATURE_ORDER
from app.db.session import session_scope
from app.services import market_data_client
from app.services.training.dataset import build_training_frame

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("train_regime_classifier")


def _build_model(classifier_type: str):
    if classifier_type == "gradient_boosting":
        return GradientBoostingClassifier(n_estimators=200, max_depth=3, learning_rate=0.05)
    return RandomForestClassifier(
        n_estimators=300, max_depth=8, min_samples_leaf=10, class_weight="balanced", n_jobs=-1
    )


async def fetch_training_data(symbol: str, exchange: str, timeframe: str, lookback_days: int):
    settings = get_settings()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    async with session_scope() as session:
        df = await market_data_client.fetch_range_bars_via_db(
            session, symbol, exchange, timeframe, start, end
        )
    return df, settings


def train_and_save(df, settings, classifier_type: str, out_path: str) -> dict:
    frame = build_training_frame(df, settings)
    if frame.empty:
        raise RuntimeError("training frame is empty — check historical data availability/date range")

    x = frame[FEATURE_ORDER].values
    y_raw = frame["label"].values

    encoder = LabelEncoder()
    y = encoder.fit_transform(y_raw)

    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.2, random_state=42, stratify=y if len(set(y)) > 1 else None
    )

    model = _build_model(classifier_type)
    model.fit(x_train, y_train)
    test_accuracy = float(model.score(x_test, y_test))
    logger.info("held-out accuracy vs rule-based labels: %.4f", test_accuracy)

    version = f"{classifier_type}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    bundle = {
        "model": model,
        "label_encoder": encoder,
        "feature_order": FEATURE_ORDER,
        "version": version,
        "test_accuracy": test_accuracy,
        "n_train_samples": len(x_train),
    }

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, out)
    logger.info("saved model bundle to %s (version=%s)", out, version)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the regime detection ML classifier")
    parser.add_argument("--symbol", default="NIFTY50")
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--lookback-days", type=int, default=730)
    parser.add_argument("--classifier-type", choices=["random_forest", "gradient_boosting"], default="random_forest")
    parser.add_argument("--out", default="models/regime_classifier.joblib")
    args = parser.parse_args()

    df, settings = asyncio.run(
        fetch_training_data(args.symbol, args.exchange, args.timeframe, args.lookback_days)
    )
    if df.empty:
        raise SystemExit(
            f"no historical bars found for {args.symbol}:{args.timeframe} in the last "
            f"{args.lookback_days} days — backfill market_data first"
        )
    train_and_save(df, settings, args.classifier_type, args.out)


if __name__ == "__main__":
    main()
