"""Trade intents API endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_any_role
from app.core.logging import get_logger
from app.db.repository import IntentRepository
from app.db.session import get_db
from app.models.domain import AggregatedSignal, TradeAction
from app.schemas.api import (
    AuditLogResponse,
    ManualSignalRequest,
    PaginationMeta,
    TradeIntentListResponse,
    TradeIntentResponse,
)
from app.utils.app_state import get_orchestrator_service

router = APIRouter(prefix="/intents", tags=["intents"])
log = get_logger(__name__)


@router.get("", response_model=TradeIntentListResponse)
async def list_intents(
    symbol: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    portfolio_id: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user = Depends(get_current_user),
):
    """List trade intents with optional filters."""
    repo = IntentRepository(db)
    rows, total = await repo.list_intents(
        symbol=symbol,
        status=status,
        portfolio_id=portfolio_id,
        since=since,
        page=page,
        page_size=page_size,
    )
    return TradeIntentListResponse(
        items=[TradeIntentResponse.model_validate(r) for r in rows],
        meta=PaginationMeta(page=page, page_size=page_size, total=total),
    )


@router.get("/{intent_id}", response_model=TradeIntentResponse)
async def get_intent(intent_id: str, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """Retrieve a single trade intent by intent_id."""
    repo = IntentRepository(db)
    row = await repo.get_by_intent_id(intent_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intent '{intent_id}' not found",
        )
    return TradeIntentResponse.model_validate(row)


@router.get("/{intent_id}/audit", response_model=AuditLogResponse)
async def get_intent_audit(intent_id: str, db: AsyncSession = Depends(get_db), _user = Depends(get_current_user)):
    """Return full eligibility check audit trail for an intent."""
    repo = IntentRepository(db)
    intent = await repo.get_by_intent_id(intent_id)
    if not intent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intent '{intent_id}' not found",
        )
    checks = await repo.get_audit_for_intent(intent_id)
    from app.schemas.api import AuditCheckResponse
    return AuditLogResponse(
        intent_id=intent_id,
        symbol=intent.symbol,
        checks=[AuditCheckResponse.model_validate(c) for c in checks],
    )


@router.post("", response_model=TradeIntentResponse, status_code=status.HTTP_201_CREATED)
async def inject_signal(
    body: ManualSignalRequest,
    db: AsyncSession = Depends(get_db),
    _user = Depends(require_any_role(["trader", "admin"])),
):
    """
    Manually inject a signal into the orchestration pipeline.
    Useful for testing, backtests, and manual overrides.
    """
    from datetime import timezone

    svc = get_orchestrator_service()
    signal = AggregatedSignal(
        symbol=body.symbol,
        timeframe=body.timeframe,
        final_signal=body.action,
        confidence=body.confidence,
        contributors=body.contributors,
        regime=body.regime,
        net_score=body.net_score,
        agreement_ratio=body.agreement_ratio,
        votes={},
        timestamp=datetime.now(timezone.utc),
    )

    log.info(
        "manual_signal_injection",
        symbol=body.symbol,
        action=body.action.value,
        confidence=body.confidence,
    )

    intent = await svc.handle_signal(signal=signal, db=db)

    repo = IntentRepository(db)
    row = await repo.get_by_intent_id(intent.intent_id)
    if not row:
        # Return from domain object if DB row not yet visible
        return TradeIntentResponse(
            intent_id=intent.intent_id,
            correlation_id=intent.correlation_id,
            symbol=intent.symbol,
            timeframe=intent.timeframe,
            action=intent.action,
            status=intent.status,
            confidence=intent.confidence,
            allocation_inr=intent.allocation_inr,
            risk_percent=intent.risk_percent,
            market_regime=intent.market_regime,
            rejection_reasons=intent.rejection_reasons,
            rejection_detail=intent.rejection_detail,
            contributors=intent.contributors,
            net_score=intent.net_score,
            agreement_ratio=intent.agreement_ratio,
            portfolio_id=intent.portfolio_id,
            created_at=intent.created_at,
        )
    return TradeIntentResponse.model_validate(row)
