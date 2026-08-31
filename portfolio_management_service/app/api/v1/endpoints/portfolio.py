"""
Portfolio REST endpoints.

GET /portfolio/snapshot           — authoritative portfolio snapshot (risk_engine / dashboard)
GET /portfolio/positions          — all open positions with MTM P&L
GET /portfolio/positions/{symbol} — single position detail
GET /portfolio/exposure           — gross/net exposure breakdown
GET /portfolio/lots/{symbol}      — FIFO lot detail for a symbol
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import CurrentUser, get_current_user
from app.core.logging import get_logger
from app.db import repository as repo
from app.db.session import pool
from app.services.mtm_service import get_portfolio_totals, refresh_all_positions
from app.services.snapshot_service import build_snapshot

log = get_logger(__name__)
router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/snapshot")
async def get_snapshot(
    refresh: bool = Query(
        default=True,
        description="Refresh MTM prices before returning snapshot",
    ),
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Authoritative portfolio snapshot.

    risk_engine_service (8007) should call this endpoint, NOT broker_service (8003).
    8009 is canonical source of truth for position/portfolio state.

    refresh=True (default): fetches live LTP before computing.
    refresh=False: returns current DB state (use for high-frequency polling).
    """
    snapshot = await build_snapshot(refresh_mtm=refresh)
    return snapshot.model_dump(mode="json")


@router.get("/positions")
async def list_positions(
    include_flat: bool = Query(default=False),
    _user: CurrentUser = Depends(get_current_user),
):
    """List all positions. By default excludes zero-quantity (flat) positions."""
    positions = await repo.list_positions(include_flat=include_flat)
    return {
        "positions": [p.model_dump(mode="json") for p in positions],
        "count": len(positions),
    }


@router.get("/positions/{symbol}")
async def get_position(
    symbol: str,
    refresh_mtm: bool = Query(default=False),
    _user: CurrentUser = Depends(get_current_user),
):
    """Get current position for a single symbol, optionally refreshing MTM."""
    if refresh_mtm:
        await refresh_all_positions()

    position = await repo.get_position(symbol.upper())
    if position is None:
        raise HTTPException(
            status_code=404, detail=f"No position found for {symbol.upper()}"
        )
    return position.model_dump(mode="json")


@router.get("/exposure")
async def get_exposure(_user: CurrentUser = Depends(get_current_user)):
    """Portfolio-level exposure: gross, net, per-symbol concentration."""
    positions = await repo.list_positions(include_flat=False)
    totals = await get_portfolio_totals(positions)
    total_value = float(totals["total_value_inr"])

    by_symbol = [
        {
            "symbol": p.symbol,
            "net_quantity": p.net_quantity,
            "market_value_inr": float(p.market_value_inr),
            "weight_pct": (
                float(p.market_value_inr) / total_value * 100.0
                if total_value > 0
                else 0.0
            ),
        }
        for p in sorted(
            positions, key=lambda x: abs(float(x.market_value_inr)), reverse=True
        )
    ]

    return {
        "gross_exposure_inr": float(totals["gross_exposure_inr"]),
        "net_exposure_inr": float(totals["net_exposure_inr"]),
        "gross_exposure_pct": totals["gross_exposure_pct"],
        "total_value_inr": total_value,
        "open_position_count": totals["open_position_count"],
        "by_symbol": by_symbol,
    }


@router.get("/lots/{symbol}")
async def get_lots(
    symbol: str,
    include_closed: bool = Query(default=False),
    _user: CurrentUser = Depends(get_current_user),
):
    """
    FIFO lot detail for a symbol.
    Useful for STCG/LTCG tax computation and audit reporting.
    """
    sym = symbol.upper()
    async with pool.acquire() as conn:
        if include_closed:
            rows = await conn.fetch(
                "SELECT * FROM pm_lots WHERE symbol = $1 ORDER BY opened_at", sym
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM pm_lots WHERE symbol = $1 AND status != 'CLOSED' ORDER BY opened_at",
                sym,
            )
    lots = [dict(r) for r in rows]
    return {"symbol": sym, "lots": lots, "count": len(lots)}
