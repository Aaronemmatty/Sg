"""XGBoost trainer — direction classification & return regression."""
from __future__ import annotations

from typing import Any

import joblib
import numpy as np
import xgboost as xgb

from app.models.domain import ModelType
from app.training.base import BaseTrainer


class XGBoostTrainer(BaseTrainer):
    model_type = ModelType.XGBOOST

    def _default_params(self) -> dict[str, Any]:
        return {
            "n_estimators": 300,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "min_child_weight": 5,
            "gamma": 0.1,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "tree_method": "hist",
            "random_state": 42,
        }

    def _objective(self, trial, X_train, y_train, X_val, y_val) -> float:
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 100, 600),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 20),
            "gamma": trial.suggest_float("gamma", 0.0, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
            "tree_method": "hist",
            "random_state": 42,
            "verbosity": 0,
        }
        n_classes = len(np.unique(y_train))
        is_clf = n_classes <= 5

        if is_clf:
            params["objective"] = "multi:softprob"
            params["num_class"] = n_classes
            model = xgb.XGBClassifier(**params)
        else:
            params["objective"] = "reg:squarederror"
            model = xgb.XGBRegressor(**params)

        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
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
        p = {**params, "verbosity": 0}

        if is_clf:
            p["objective"] = "multi:softprob"
            p["num_class"] = n_classes
            model = xgb.XGBClassifier(**p)
        else:
            p["objective"] = "reg:squarederror"
            model = xgb.XGBRegressor(**p)

        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        return model

    def _predict_proba(self, model: Any, X: np.ndarray) -> np.ndarray:
        if hasattr(model, "predict_proba"):
            return model.predict_proba(X)
        else:
            preds = model.predict(X)
            # Convert scalar regression output to (n, 1) array
            return preds.reshape(-1, 1)

    def _save_model(self, model: Any, path: str) -> None:
        joblib.dump(model, path)

    def _load_model(self, path: str) -> Any:
        return joblib.load(path)
