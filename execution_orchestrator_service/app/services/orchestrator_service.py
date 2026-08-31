"""
Orchestrator Service — top-level coordinator.

Calls pipeline → persists intent + audit → publishes to Redis.
Used by both the Redis consumer and the REST endpoint (manual injection).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.metrics import INTENTS_PERSIST_ERRORS, INTENTS_PERSISTED
from app.db.repository import IntentRepository
from app.models.domain import AggregatedSignal, TradeIntent
from app.orchestrator.pipeline import OrchestratorPipeline
from app.publishers.intent_publisher import IntentPublisher
from app.services.state_fetcher import StateFetcher

log = get_logger(__name__)


class OrchestratorService:
    """
    Stateless service — one instance shared across the app lifetime.
    regime_cache is a mutable dict shared by reference with the
    regime consumer so it always holds the latest regime per symbol.
    """

    def __init__(self, regime_cache: dict[str, str]) -> None:
        self._regime_cache = regime_cache
        self._fetcher = StateFetcher()
        self._publisher = IntentPublisher()

    async def handle_signal(
        self,
        signal: AggregatedSignal,
        db: AsyncSession,
        portfolio_id: Optional[str] = None,
    ) -> TradeIntent:
        """
        Full round-trip:
          1. Run orchestration pipeline
          2. Persist intent + audit to DB
          3. Publish intent to Redis
        Returns the produced TradeIntent.
        """
        pipeline = OrchestratorPipeline(
            state_fetcher=self._fetcher,
            regime_cache=self._regime_cache,
        )

        intent, checks, portfolio, risk = await pipeline.process(signal, portfolio_id)

        repo = IntentRepository(db)

        # ── Persist ───────────────────────────────────────────────────────────
        try:
            await repo.persist_intent(
                intent,
                portfolio_value_inr=portfolio.total_value_inr,
                daily_loss_inr=risk.daily_loss_inr,
                drawdown_pct=risk.drawdown_pct,
                open_intents_snapshot=risk.open_intents_count,
            )
            await repo.persist_audit_checks(intent.intent_id, signal.symbol, checks)
            await db.commit()
            INTENTS_PERSISTED.labels(
                symbol=signal.symbol, status=intent.status.value
            ).inc()
        except Exception as exc:
            log.error(
                "intent_persist_failed",
                intent_id=intent.intent_id,
                symbol=signal.symbol,
                error=str(exc),
                exc_info=True,
            )
            INTENTS_PERSIST_ERRORS.labels(symbol=signal.symbol).inc()
            await db.rollback()
            # Continue — publish even if DB write fails (best-effort persistence)

        # ── Publish ───────────────────────────────────────────────────────────
        await self._publisher.publish(intent)

        return intent
