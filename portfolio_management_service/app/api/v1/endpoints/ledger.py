"""
Trade ledger and historical snapshot endpoints.

GET /ledger/trades            — immutable fill event log
GET /ledger/snapshots         — historical portfolio snapshots list
GET /ledger/snapshots/latest  — most recent persisted snapshot
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.auth import CurrentUser, get_current_user
from app.db import repository as repo

router = APIRouter(prefix="/ledger", tags=["ledger"])


@router.get("/trades")
async def list_trades(
    symbol: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=1000),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(get_current_user),
):
    """Immutable fill event log — source of truth for all executed trades."""
    rows = await repo.list_trade_ledger(symbol=symbol, since=since, limit=limit, offset=offset)
    return {"trades": rows, "count": len(rows)}


@router.get("/snapshots")
async def list_snapshots(
    since: datetime | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    _user: CurrentUser = Depends(get_current_user),
):
    """Historical portfolio snapshot index (header fields only, no positions detail)."""
    rows = await repo.list_snapshots(since=since, limit=limit, offset=offset)
    return {"snapshots": rows, "count": len(rows)}


@router.get("/snapshots/latest")
async def get_latest_snapshot(_user: CurrentUser = Depends(get_current_user)):
    """Most recently persisted portfolio snapshot (full detail with positions)."""
    row = await repo.get_latest_snapshot()
    return row or {}
