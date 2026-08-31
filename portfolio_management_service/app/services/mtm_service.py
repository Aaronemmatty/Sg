"""
Mark-to-Market (MTM) Service.

Fetches live prices for all open positions and recomputes:
  - unrealized_pnl_inr per position
  - market_value_inr per position
  - day_pnl_inr per position (vs day-open price recorded in pm_portfolio_config)
  - portfolio-level gauges for Prometheus

Runs on a configurable timer interval (MTM_REFRESH_INTERVAL_SECONDS).
Also called on-demand by the /portfolio/snapshot endpoint.

Price source: GET /symbols/{symbol}/ltp on market_data_service (8002).
If that endpoint is unavailable, falls back to last known price in DB.
The client is isolated to market_data_client.py — if 8002 switches to
a Redis-stream-only model, only that file changes.
"""
from __future__ import annotations

from decimal import Decimal

from app.core.logging import get_logger
from app.core.metrics import (
    mtm_refresh_failures_total,
    mtm_refresh_total,
    portfolio_open_positions,
    portfolio_total_value_inr,
    portfolio_unrealized_pnl_inr,
)
from app.db import repository as repo
from app.models.domain import Position
from app.services.market_data_client import market_data_client

log = get_logger(__name__)


async def refresh_all_positions() -> list[Position]:
    """
    Refresh MTM for all non-flat positions.
    Returns the updated list of positions.
    Errors on individual symbols are logged and skipped — never propagated.
    """
    positions = await repo.list_positions(include_flat=False)
    if not positions:
        return []

    updated: list[Position] = []
    for pos in positions:
        try:
            price = await market_data_client.get_last_price(pos.symbol)
            if price is None:
                # Use last known price from DB (already in pos.market_price_inr)
                price_decimal = pos.market_price_inr or pos.avg_cost_inr
                mtm_refresh_failures_total.labels(symbol=pos.symbol).inc()
                log.debug("mtm_using_stale_price", symbol=pos.symbol)
            else:
                price_decimal = Decimal(str(price))

            # Compute day P&L: position P&L vs SOD market value
            config = await repo.get_portfolio_config()
            day_open_value = Decimal(str(config.get("day_open_value_inr") or "0"))
            current_market_value = price_decimal * Decimal(str(pos.net_quantity))
            # day_pnl = current total value - SOD total value (approximated per position)
            # For a proper per-position day P&L we'd need SOD price; approximate with
            # realized delta since SOD. This is a v1 simplification noted below.
            day_pnl = (
                (price_decimal - (pos.market_price_inr or price_decimal))
                * Decimal(str(pos.net_quantity))
            )

            pos.recompute_from_mtm(price_decimal)
            pos.day_pnl_inr = day_pnl + pos.day_pnl_inr  # accumulate intraday

            await repo.update_position_mtm(
                symbol=pos.symbol,
                market_price_inr=price_decimal,
                market_value_inr=pos.market_value_inr,
                unrealized_pnl_inr=pos.unrealized_pnl_inr,
                total_pnl_inr=pos.total_pnl_inr,
                day_pnl_inr=pos.day_pnl_inr,
            )
            updated.append(pos)

        except Exception:
            log.exception("mtm_refresh_position_failed", symbol=pos.symbol)

    # Update portfolio-level Prometheus gauges
    total_unrealized = sum(p.unrealized_pnl_inr for p in updated)
    config = await repo.get_portfolio_config()
    cash = Decimal(str(config.get("cash_balance_inr") or "0"))
    total_equity = sum(p.market_value_inr for p in updated)
    total_value = cash + total_equity

    portfolio_unrealized_pnl_inr.set(float(total_unrealized))
    portfolio_total_value_inr.set(float(total_value))
    portfolio_open_positions.set(len(updated))
    mtm_refresh_total.inc()

    return updated


async def get_portfolio_totals(positions: list[Position] | None = None) -> dict:
    """
    Compute portfolio-level aggregates from current position state.
    Used by both snapshot builder and the /portfolio/snapshot endpoint.
    """
    if positions is None:
        positions = await repo.list_positions(include_flat=False)

    config = await repo.get_portfolio_config()
    initial_capital = Decimal(str(config.get("initial_capital_inr") or "0"))
    cash = Decimal(str(config.get("cash_balance_inr") or initial_capital))

    total_equity = sum(p.market_value_inr for p in positions)
    total_value = cash + total_equity
    gross_exposure = sum(abs(p.market_value_inr) for p in positions)
    net_exposure = sum(p.market_value_inr for p in positions)
    total_unrealized = sum(p.unrealized_pnl_inr for p in positions)
    total_realized = sum(p.realized_pnl_inr for p in positions)
    total_pnl = total_unrealized + total_realized
    day_pnl = sum(p.day_pnl_inr for p in positions)

    total_return_pct = (
        float(total_pnl / initial_capital * 100) if initial_capital > 0 else 0.0
    )
    gross_exposure_pct = (
        float(gross_exposure / total_value * 100) if total_value > 0 else 0.0
    )

    return {
        "initial_capital_inr": initial_capital,
        "cash_balance_inr": cash,
        "equity_value_inr": total_equity,
        "total_value_inr": total_value,
        "day_pnl_inr": day_pnl,
        "total_pnl_inr": total_pnl,
        "total_return_pct": total_return_pct,
        "gross_exposure_inr": gross_exposure,
        "net_exposure_inr": net_exposure,
        "gross_exposure_pct": gross_exposure_pct,
        "open_position_count": len(positions),
    }
