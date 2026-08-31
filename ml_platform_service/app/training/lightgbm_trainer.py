"""LightGBM trainer — faster than XGBoost on large feature sets."""
from __future__ import annotations

from typing import Any

import joblib
import lightgbm as lgb
import numpy as np

from app.models.domain import ModelType
from app.training.base import BaseTrainer


class LightGBMTrainer(BaseTrainer):
    model_type = ModelType.LIGHTGBM

    def _default_params(self) -> dict[str, Any]:
        return {
            "n_estimators": 300,
            "max_depth": -1,
            "num_leaves": 31,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_samples": 20,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "random_state": 42,
            "verbosity": -1,
        }

    def _objective(self, trial, X_train, y_train, X_val, y_val) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 600),
            "num_leaves": trial.suggest_int("num_leaves", 20, 150),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
            "random_state": 42,
            "verbosity": -1,
        }
        n_classes = len(np.unique(y_train))
        is_clf = n_classes <= 5

        callbacks = [lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=-1)]

        if is_clf:
            params["objective"] = "multiclass"
            params["num_class"] = n_classes
            params["metric"] = "multi_logloss"
            model = lgb.LGBMClassifier(**params)
        else:
            params["objective"] = "regression"
            params["metric"] = "rmse"
            model = lgb.LGBMRegressor(**params)

        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            callbacks=callbacks,
        )

        if is_clf:
            preds = np.argmax(model.predict_proba(X_val), axis=1)
            from sklearn.metrics import accuracy_score
            return float(accuracy_score(y_val.astype(int), preds.astype(int)))
        else:
            from sklearn.metrics import r2_score
            return max(0.0, float(r2_score(y_val, model.predict(X_val))))

    def _fit(self, X_train, y_train, X_val, y_val, params) -> Any:
        n_classes = len(np.unique(y_train))
        is_clf = n_classes <= 5
        callbacks = [lgb.early_stopping(30, verbose=False), lgb.log_evaluation(period=-1)]

        if is_clf:
            p = {**params, "objective": "multiclass", "num_class": n_classes}
            model = lgb.LGBMClassifier(**p)
        else:
            p = {**params, "objective": "regression"}
            model = lgb.LGBMRegressor(**p)

        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], callbacks=callbacks)
        return model

    def _predict_proba(self, model: Any, X: np.ndarray) -> np.ndarray:
        if hasattr(model, "predict_proba"):
            return model.predict_proba(X)
        preds = model.predict(X)
        return preds.reshape(-1, 1)

    def _save_model(self, model: Any, path: str) -> None:
        joblib.dump(model, path)

    def _load_model(self, path: str) -> Any:
        return joblib.load(path)
