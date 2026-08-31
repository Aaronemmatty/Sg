"""
Training Dispatcher.

Routes TrainingConfig to the correct trainer implementation,
manages the async job queue, and enforces one concurrent training
job per symbol to prevent resource contention.
"""
from __future__ import annotations

import asyncio
from typing import ClassVar

from app.core.logging import get_logger
from app.models.domain import ModelType, TrainingConfig, TrainingJob
from app.training.base import BaseTrainer
from app.training.lightgbm_trainer import LightGBMTrainer
from app.training.lstm_trainer import LSTMTrainer
from app.training.transformer_trainer import TransformerTrainer
from app.training.xgboost_trainer import XGBoostTrainer

log = get_logger(__name__)

_TRAINERS: dict[ModelType, BaseTrainer] = {
    ModelType.XGBOOST: XGBoostTrainer(),
    ModelType.LIGHTGBM: LightGBMTrainer(),
    ModelType.LSTM: LSTMTrainer(),
    ModelType.TRANSFORMER: TransformerTrainer(),
}


class TrainingDispatcher:
    """
    Singleton dispatcher that runs training jobs in a background asyncio pool.

    - Jobs run in a thread pool (training is CPU-bound / blocking).
    - One active job per (symbol, model_type) pair to prevent duplicate runs.
    - Queue is in-memory; on restart, pending jobs are re-submitted via
      the scheduled retraining loop.
    """

    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()
    _active: ClassVar[dict[str, asyncio.Task]] = {}  # key: "{symbol}:{model_type}"

    @classmethod
    async def submit(cls, config: TrainingConfig) -> str:
        """
        Submit a training job. Returns "queued", "started", or "already_running".
        Actual training runs in a background asyncio Task via thread pool.
        """
        key = f"{config.symbol}:{config.model_type.value}"
        async with cls._lock:
            if key in cls._active and not cls._active[key].done():
                log.info("training_job_already_running", key=key)
                return "already_running"

            task = asyncio.create_task(cls._run_job(config, key))
            cls._active[key] = task
            log.info(
                "training_job_submitted",
                key=key,
                job_id=str(config.job_id),
                n_trials=config.n_trials,
            )
            return "started"

    @classmethod
    async def _run_job(cls, config: TrainingConfig, key: str) -> TrainingJob:
        trainer = _TRAINERS.get(config.model_type)
        if trainer is None:
            raise ValueError(f"No trainer registered for {config.model_type}")
        try:
            loop = asyncio.get_event_loop()
            # Run blocking training in a thread pool so the event loop stays responsive
            job = await loop.run_in_executor(None, _run_sync, trainer, config)
            return job
        finally:
            async with cls._lock:
                cls._active.pop(key, None)

    @classmethod
    def active_jobs(cls) -> list[str]:
        return [k for k, t in cls._active.items() if not t.done()]


def _run_sync(trainer: BaseTrainer, config: TrainingConfig) -> TrainingJob:
    """Synchronous wrapper for running async trainer.run() in a thread."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(trainer.run(config))
    finally:
        loop.close()
