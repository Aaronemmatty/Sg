"""Repository — trade_intents and audit_logs persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.domain import EligibilityResult, IntentStatus, TradeIntent
from app.models.orm import OrchestratorAuditLogORM, TradeIntentORM

log = get_logger(__name__)


class IntentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Write ─────────────────────────────────────────────────────────────────

    async def persist_intent(
        self,
        intent: TradeIntent,
        portfolio_value_inr: Optional[float] = None,
        daily_loss_inr: Optional[float] = None,
        drawdown_pct: Optional[float] = None,
        open_intents_snapshot: Optional[int] = None,
    ) -> TradeIntentORM:
        orm = TradeIntentORM(
            intent_id=intent.intent_id,
            correlation_id=intent.correlation_id,
            symbol=intent.symbol,
            timeframe=intent.timeframe or None,
            action=intent.action.value,
            status=intent.status.value,
            rejection_reasons=(
                [r.value for r in intent.rejection_reasons]
                if intent.rejection_reasons
                else None
            ),
            rejection_detail=intent.rejection_detail,
            confidence=intent.confidence,
            net_score=intent.net_score,
            agreement_ratio=intent.agreement_ratio,
            contributors=intent.contributors or None,
            allocation_inr=intent.allocation_inr,
            risk_percent=intent.risk_percent,
            market_regime=intent.market_regime,
            portfolio_id=intent.portfolio_id,
            snapshot_portfolio_value_inr=portfolio_value_inr,
            snapshot_daily_loss_inr=daily_loss_inr,
            snapshot_drawdown_pct=drawdown_pct,
            snapshot_open_intents=open_intents_snapshot,
            signal_timestamp=intent.signal_timestamp,
        )
        self._session.add(orm)
        await self._session.flush()
        log.info(
            "intent_persisted",
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            status=intent.status.value,
        )
        return orm

    async def persist_audit_checks(
        self,
        intent_id: str,
        symbol: str,
        checks: list[EligibilityResult],
    ) -> None:
        rows = [
            OrchestratorAuditLogORM(
                intent_id=intent_id,
                symbol=symbol,
                check_name=c.check_name,
                passed=c.passed,
                reason=c.reason.value if c.reason else None,
                detail=c.detail,
            )
            for c in checks
        ]
        self._session.add_all(rows)
        await self._session.flush()

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_by_intent_id(self, intent_id: str) -> Optional[TradeIntentORM]:
        result = await self._session.execute(
            select(TradeIntentORM).where(TradeIntentORM.intent_id == intent_id)
        )
        return result.scalar_one_or_none()

    async def list_intents(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        portfolio_id: Optional[str] = None,
        since: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[TradeIntentORM], int]:
        q = select(TradeIntentORM)
        if symbol:
            q = q.where(TradeIntentORM.symbol == symbol)
        if status:
            q = q.where(TradeIntentORM.status == status)
        if portfolio_id:
            q = q.where(TradeIntentORM.portfolio_id == portfolio_id)
        if since:
            q = q.where(TradeIntentORM.created_at >= since)

        count_q = select(func.count()).select_from(q.subquery())
        total = (await self._session.execute(count_q)).scalar_one()

        q = q.order_by(TradeIntentORM.created_at.desc())
        q = q.offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(q)).scalars().all()
        return list(rows), total

    async def count_open_intents(self, portfolio_id: Optional[str] = None) -> int:
        q = select(func.count()).where(
            TradeIntentORM.status == IntentStatus.ELIGIBLE.value
        )
        if portfolio_id:
            q = q.where(TradeIntentORM.portfolio_id == portfolio_id)
        return (await self._session.execute(q)).scalar_one()

    async def get_audit_for_intent(
        self, intent_id: str
    ) -> list[OrchestratorAuditLogORM]:
        result = await self._session.execute(
            select(OrchestratorAuditLogORM)
            .where(OrchestratorAuditLogORM.intent_id == intent_id)
            .order_by(OrchestratorAuditLogORM.created_at)
        )
        return list(result.scalars().all())
