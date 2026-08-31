"""
LSTM trainer.

Uses PyTorch when available; falls back to sklearn MLPClassifier when
torch is not installed or fails to load (e.g. missing CUDA shared libs).
"""
from __future__ import annotations

import importlib
import importlib.util
from typing import Any

import joblib
import numpy as np

from app.core.logging import get_logger
from app.models.domain import ModelType
from app.training.base import BaseTrainer

log = get_logger(__name__)


def _check_torch() -> bool:
    """Return True only if torch can actually be imported without error."""
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

    class _LSTMModel(nn.Module):
        def __init__(self, input_size: int, hidden_size: int, num_layers: int,
                     dropout: float, n_classes: int):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size, hidden_size, num_layers,
                batch_first=True,
                dropout=dropout if num_layers > 1 else 0.0,
            )
            self.dropout = nn.Dropout(dropout)
            self.fc = nn.Linear(hidden_size, n_classes)

        def forward(self, x):
            out, _ = self.lstm(x)
            out = self.dropout(out[:, -1, :])
            return self.fc(out)


class LSTMTrainer(BaseTrainer):
    model_type = ModelType.LSTM

    def _default_params(self) -> dict[str, Any]:
        return {
            "hidden_size": 128,
            "num_layers": 2,
            "dropout": 0.2,
            "learning_rate": 1e-3,
            "batch_size": 64,
            "epochs": 50,
        }

    def _objective(self, trial, X_train, y_train, X_val, y_val) -> float:
        if not _TORCH_AVAILABLE:
            return self._sklearn_objective(trial, X_train, y_train, X_val, y_val)
        params = {
            "hidden_size": trial.suggest_categorical("hidden_size", [64, 128, 256]),
            "num_layers": trial.suggest_int("num_layers", 1, 3),
            "dropout": trial.suggest_float("dropout", 0.1, 0.5),
            "learning_rate": trial.suggest_float("learning_rate", 1e-4, 1e-2, log=True),
            "batch_size": trial.suggest_categorical("batch_size", [32, 64, 128]),
            "epochs": 20,
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

    # ── PyTorch helpers ───────────────────────────────────────────────────────

    def _torch_train_eval(self, X_tr, y_tr, X_val, y_val, params) -> float:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset

        n_classes = len(np.unique(y_tr))
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = _LSTMModel(X_tr.shape[-1], params["hidden_size"],
                           params["num_layers"], params["dropout"], n_classes).to(device)
        Xt = torch.FloatTensor(X_tr).to(device)
        yt = torch.LongTensor(y_tr.astype(int)).to(device)
        Xv = torch.FloatTensor(X_val).to(device)
        loader = DataLoader(TensorDataset(Xt, yt), batch_size=params["batch_size"], shuffle=True)
        optim = torch.optim.Adam(model.parameters(), lr=params["learning_rate"])
        criterion = nn.CrossEntropyLoss()
        model.train()
        for _ in range(params["epochs"]):
            for xb, yb in loader:
                optim.zero_grad()
                criterion(model(xb), yb).backward()
                optim.step()
        model.eval()
        with torch.no_grad():
            preds = model(Xv).argmax(dim=1).cpu().numpy()
        from sklearn.metrics import accuracy_score
        return float(accuracy_score(y_val.astype(int), preds))

    def _torch_fit(self, X_tr, y_tr, X_val, y_val, params) -> dict:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset

        n_classes = len(np.unique(y_tr))
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = _LSTMModel(X_tr.shape[-1], params["hidden_size"],
                           params["num_layers"], params["dropout"], n_classes).to(device)
        Xt = torch.FloatTensor(X_tr).to(device)
        yt = torch.LongTensor(y_tr.astype(int)).to(device)
        Xv = torch.FloatTensor(X_val).to(device)
        yv = torch.LongTensor(y_val.astype(int)).to(device)
        loader = DataLoader(TensorDataset(Xt, yt), batch_size=params["batch_size"], shuffle=True)
        optim = torch.optim.Adam(model.parameters(), lr=params["learning_rate"])
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
                if patience >= 10:
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

    # ── Sklearn fallback ──────────────────────────────────────────────────────

    def _sklearn_objective(self, trial, X_tr, y_tr, X_val, y_val) -> float:
        from sklearn.neural_network import MLPClassifier
        params = {
            "hidden_layer_sizes": trial.suggest_categorical(
                "hidden_layer_sizes", [(64,), (128,), (64, 64), (128, 64)]
            ),
            "alpha": trial.suggest_float("alpha", 1e-5, 1e-1, log=True),
        }
        Xf = X_tr.reshape(X_tr.shape[0], -1)
        Xvf = X_val.reshape(X_val.shape[0], -1)
        mlp = MLPClassifier(**params, max_iter=50, random_state=42)
        mlp.fit(Xf, y_tr.astype(int))
        preds = mlp.predict(Xvf)
        from sklearn.metrics import accuracy_score
        return float(accuracy_score(y_val.astype(int), preds))

    def _sklearn_fit(self, X_tr, y_tr, params) -> Any:
        from sklearn.neural_network import MLPClassifier
        log.warning("lstm_torch_unavailable_using_mlp_fallback")
        Xf = X_tr.reshape(X_tr.shape[0], -1)
        mlp = MLPClassifier(
            hidden_layer_sizes=(params.get("hidden_size", 128), 64),
            max_iter=100, random_state=42,
        )
        mlp.fit(Xf, y_tr.astype(int))
        return mlp
