"""
Transformer trainer for time-series classification.
Falls back to sklearn GradientBoostingClassifier if torch unavailable.
"""
from __future__ import annotations

import importlib
import importlib.util
import math
from typing import Any

import joblib
import numpy as np

from app.core.logging import get_logger
from app.models.domain import ModelType
from app.training.base import BaseTrainer

log = get_logger(__name__)


def _check_torch() -> bool:
    if importlib.util.find_spec("torch") is None:
        return False
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


_TORCH_AVAILABLE = _check_torch()

if _TORCH_AVAILABLE:
    import torch
    import torch.nn as nn

    class _PositionalEncoding(nn.Module):
        def __init__(self, d_model: int, max_len: int = 512, dropout: float = 0.1):
            super().__init__()
            self.dropout = nn.Dropout(dropout)
            pe = torch.zeros(max_len, d_model)
            pos = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
            div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
            pe[:, 0::2] = torch.sin(pos * div)
            pe[:, 1::2] = torch.cos(pos * div)
            self.register_buffer("pe", pe.unsqueeze(0))

        def forward(self, x):
            return self.dropout(x + self.pe[:, :x.size(1), :])

    class _TransformerModel(nn.Module):
        def __init__(self, input_size, d_model, nhead, num_layers, dropout, n_classes):
            super().__init__()
            self.input_proj = nn.Linear(input_size, d_model)
            self.pos_enc = _PositionalEncoding(d_model, dropout=dropout)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model, nhead=nhead, dim_feedforward=d_model * 4,
                dropout=dropout, batch_first=True, norm_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
            self.norm = nn.LayerNorm(d_model)
            self.classifier = nn.Sequential(
                nn.Linear(d_model, d_model // 2), nn.ReLU(),
                nn.Dropout(dropout), nn.Linear(d_model // 2, n_classes),
            )

        def forward(self, x):
            x = self.pos_enc(self.input_proj(x))
            return self.classifier(self.norm(self.encoder(x)).mean(dim=1))


class TransformerTrainer(BaseTrainer):
    model_type = ModelType.TRANSFORMER

    def _default_params(self) -> dict[str, Any]:
        return {"d_model": 64, "nhead": 4, "num_layers": 2,
                "dropout": 0.1, "learning_rate": 5e-4, "batch_size": 64, "epochs": 50}

    def _objective(self, trial, X_train, y_train, X_val, y_val) -> float:
        if not _TORCH_AVAILABLE:
            return self._sklearn_objective(trial, X_train, y_train, X_val, y_val)
        d_model = trial.suggest_categorical("d_model", [32, 64, 128])
        nhead = trial.suggest_categorical("nhead", [h for h in [2, 4, 8] if d_model % h == 0])
        params = {
            "d_model": d_model, "nhead": nhead,
            "num_layers": trial.suggest_int("num_layers", 1, 4),
            "dropout": trial.suggest_float("dropout", 0.05, 0.4),
            "learning_rate": trial.suggest_float("learning_rate", 1e-4, 5e-3, log=True),
            "batch_size": trial.suggest_categorical("batch_size", [32, 64, 128]),
            "epochs": 15,
        }
        return self._torch_train_eval(X_train, y_train, X_val, y_val, params)

    def _fit(self, X_train, y_train, X_val, y_val, params) -> Any:
        if not _TORCH_AVAILABLE:
            return self._sklearn_fit(X_train, y_train, params)
        return self._torch_fit(X_train, y_train, X_val, y_val, params)

    def _predict_proba(self, model: Any, X: np.ndarray) -> np.ndarray:
        if not _TORCH_AVAILABLE or not isinstance(model, dict):
            return model.predict_proba(X.reshape(X.shape[0], -1))
        return self._torch_predict_proba(model, X)

    def _save_model(self, model: Any, path: str) -> None:
        if _TORCH_AVAILABLE and isinstance(model, dict):
            import torch
            torch.save(model, path.replace(".pkl", ".pt"))
        else:
            joblib.dump(model, path)

    def _load_model(self, path: str) -> Any:
        if _TORCH_AVAILABLE:
            import torch
            return torch.load(path.replace(".pkl", ".pt"), weights_only=False)
        return joblib.load(path)

    def _torch_train_eval(self, X_tr, y_tr, X_val, y_val, params) -> float:
        import torch, torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
        n_classes = len(np.unique(y_tr))
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = _TransformerModel(X_tr.shape[-1], params["d_model"], params["nhead"],
                                  params["num_layers"], params["dropout"], n_classes).to(device)
        Xt = torch.FloatTensor(X_tr).to(device)
        yt = torch.LongTensor(y_tr.astype(int)).to(device)
        Xv = torch.FloatTensor(X_val).to(device)
        loader = DataLoader(TensorDataset(Xt, yt), batch_size=params["batch_size"], shuffle=True)
        optim = torch.optim.AdamW(model.parameters(), lr=params["learning_rate"], weight_decay=1e-4)
        criterion = nn.CrossEntropyLoss()
        model.train()
        for _ in range(params["epochs"]):
            for xb, yb in loader:
                optim.zero_grad()
                criterion(model(xb), yb).backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optim.step()
        model.eval()
        with torch.no_grad():
            preds = model(Xv).argmax(dim=1).cpu().numpy()
        from sklearn.metrics import accuracy_score
        return float(accuracy_score(y_val.astype(int), preds))

    def _torch_fit(self, X_tr, y_tr, X_val, y_val, params) -> dict:
        import torch, torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
        n_classes = len(np.unique(y_tr))
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = _TransformerModel(X_tr.shape[-1], params["d_model"], params["nhead"],
                                  params["num_layers"], params["dropout"], n_classes).to(device)
        Xt = torch.FloatTensor(X_tr).to(device)
        yt = torch.LongTensor(y_tr.astype(int)).to(device)
        Xv = torch.FloatTensor(X_val).to(device)
        yv = torch.LongTensor(y_val.astype(int)).to(device)
        loader = DataLoader(TensorDataset(Xt, yt), batch_size=params["batch_size"], shuffle=True)
        optim = torch.optim.AdamW(model.parameters(), lr=params["learning_rate"], weight_decay=1e-4)
        criterion = nn.CrossEntropyLoss()
        best_val, patience, best_state = float("inf"), 0, None
        for _ in range(params["epochs"]):
            model.train()
            for xb, yb in loader:
                optim.zero_grad()
                criterion(model(xb), yb).backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optim.step()
            model.eval()
            with torch.no_grad():
                vl = criterion(model(Xv), yv).item()
            if vl < best_val - 1e-4:
                best_val, patience = vl, 0
                best_state = {k: v.clone() for k, v in model.state_dict().items()}
            else:
                patience += 1
                if patience >= 8:
                    break
        if best_state:
            model.load_state_dict(best_state)
        return {"model": model, "n_classes": n_classes, "params": params}

    def _torch_predict_proba(self, model_dict: dict, X: np.ndarray) -> np.ndarray:
        import torch, torch.nn.functional as F
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model_dict["model"].to(device)
        model.eval()
        with torch.no_grad():
            return F.softmax(model(torch.FloatTensor(X).to(device)), dim=1).cpu().numpy()

    def _sklearn_objective(self, trial, X_tr, y_tr, X_val, y_val) -> float:
        from sklearn.ensemble import GradientBoostingClassifier
        params = {
            "n_estimators": trial.suggest_int("n_estimators", 50, 200),
            "max_depth": trial.suggest_int("max_depth", 3, 6),
            "learning_rate": trial.suggest_float("learning_rate", 0.05, 0.3),
        }
        Xf = X_tr.reshape(X_tr.shape[0], -1)
        Xvf = X_val.reshape(X_val.shape[0], -1)
        clf = GradientBoostingClassifier(**params, random_state=42)
        clf.fit(Xf, y_tr.astype(int))
        preds = clf.predict(Xvf)
        from sklearn.metrics import accuracy_score
        return float(accuracy_score(y_val.astype(int), preds))

    def _sklearn_fit(self, X_tr, y_tr, params) -> Any:
        from sklearn.ensemble import GradientBoostingClassifier
        log.warning("transformer_torch_unavailable_using_gbt_fallback")
        clf = GradientBoostingClassifier(n_estimators=150, max_depth=4, random_state=42)
        clf.fit(X_tr.reshape(X_tr.shape[0], -1), y_tr.astype(int))
        return clf
