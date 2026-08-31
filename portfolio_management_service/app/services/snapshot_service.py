"""
Snapshot Service.

Builds a PortfolioSnapshot from live position state, persists it to
pm_snapshots, and publishes a SNAPSHOT_READY event to sg:portfolio:events.

This endpoint is the authoritative /portfolio/snapshot source of truth —
risk_engine_service (8007) should call 8009 for portfolio state, not 8003.
"""
from __future__ import annotations

import time

from app.core.logging import get_logger
from app.core.metrics import snapshot_write_latency_seconds, snapshots_written_total
from app.db import repository as repo
from app.models.domain import (
    PerformanceWindow,
    PortfolioEvent,
    PortfolioEventType,
    PortfolioSnapshot,
    PositionSummary,
)
from app.services.mtm_service import get_portfolio_totals, refresh_all_positions
from app.services.performance_engine import compute_performance

log = get_logger(__name__)


async def build_snapshot(*, refresh_mtm: bool = True) -> PortfolioSnapshot:
    """
    Build a complete PortfolioSnapshot.

    Args:
        refresh_mtm: If True, refresh MTM prices before computing the snapshot.
                     Set to False when called at high frequency to avoid hammering
                     market_data_service.
    """
    t0 = time.perf_counter()

    positions = await (refresh_all_positions() if refresh_mtm else repo.list_positions())
    totals = await get_portfolio_totals(positions)

    # Compute position summaries with weight
    total_value = float(totals["total_value_inr"])
    position_summaries = [
        PositionSummary(
            symbol=p.symbol,
            net_quantity=p.net_quantity,
            avg_cost_inr=float(p.avg_cost_inr),
            market_price_inr=float(p.market_price_inr) if p.market_price_inr else None,
            market_value_inr=float(p.market_value_inr),
            unrealized_pnl_inr=float(p.unrealized_pnl_inr),
            realized_pnl_inr=float(p.realized_pnl_inr),
            weight_pct=(float(p.market_value_inr) / total_value * 100.0)
            if total_value > 0
            else 0.0,
        )
        for p in positions
        if not p.is_flat
    ]

    # 30d performance (included inline in every snapshot)
    try:
        perf_30d = await compute_performance(PerformanceWindow.DAYS_30)
    except Exception:
        log.warning("snapshot_perf_30d_computation_failed")
        perf_30d = None

    snapshot = PortfolioSnapshot(
        initial_capital_inr=totals["initial_capital_inr"],
        cash_balance_inr=totals["cash_balance_inr"],
        equity_value_inr=totals["equity_value_inr"],
        total_value_inr=totals["total_value_inr"],
        day_pnl_inr=totals["day_pnl_inr"],
        total_pnl_inr=totals["total_pnl_inr"],
        total_return_pct=totals["total_return_pct"],
        gross_exposure_inr=totals["gross_exposure_inr"],
        net_exposure_inr=totals["net_exposure_inr"],
        gross_exposure_pct=totals["gross_exposure_pct"],
        open_position_count=totals["open_position_count"],
        positions=position_summaries,
        performance_30d=perf_30d,
    )

    elapsed = time.perf_counter() - t0
    snapshot_write_latency_seconds.observe(elapsed)
    return snapshot


async def persist_snapshot(snapshot: PortfolioSnapshot) -> None:
    await repo.insert_snapshot(snapshot)
    snapshots_written_total.inc()
    log.info(
        "snapshot_persisted",
        snapshot_id=str(snapshot.snapshot_id),
        total_value=float(snapshot.total_value_inr),
        open_positions=snapshot.open_position_count,
    )


async def build_and_persist(*, refresh_mtm: bool = True) -> PortfolioSnapshot:
    snapshot = await build_snapshot(refresh_mtm=refresh_mtm)
    await persist_snapshot(snapshot)
    return snapshot
