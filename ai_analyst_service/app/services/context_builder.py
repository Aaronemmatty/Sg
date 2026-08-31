from __future__ import annotations

from app.clients.execution_client import ExecutionClient
from app.clients.market_data_client import MarketDataClient
from app.clients.portfolio_client import PortfolioClient
from app.clients.risk_client import RiskClient
from app.models.domain import (
    MarketSummaryRequest,
    PerformanceExplanationRequest,
    PortfolioReviewRequest,
    RiskExplanationRequest,
    TradeReviewRequest,
)


def _note_if_unavailable(label: str, result: dict, warnings: list[str]) -> None:
    if not result.get("available"):
        warnings.append(f"{label} unavailable: {result.get('reason', 'unknown error')}")


async def build_trade_review_context(
    req: TradeReviewRequest,
    execution_client: ExecutionClient,
    portfolio_client: PortfolioClient,
) -> tuple[dict, list[str]]:
    warnings: list[str] = []

    orders = await execution_client.get_recent_orders(symbol=req.symbol, days=req.lookback_days)
    _note_if_unavailable("recent orders (execution_engine_service)", orders, warnings)

    order_detail = None
    if req.trade_id:
        order_detail = await execution_client.get_order(str(req.trade_id))
        _note_if_unavailable("order detail (execution_engine_service)", order_detail, warnings)

    trades = await portfolio_client.get_recent_trades(limit=20)
    _note_if_unavailable("trade ledger (portfolio_management_service)", trades, warnings)

    position = None
    if req.symbol:
        position = await portfolio_client.get_position(req.symbol)
        _note_if_unavailable("position detail (portfolio_management_service)", position, warnings)

    context = {
        "requested_trade_id": str(req.trade_id) if req.trade_id else None,
        "requested_symbol": req.symbol,
        "lookback_days": req.lookback_days,
        "order_detail": order_detail,
        "recent_orders": orders,
        "trade_ledger": trades,
        "current_position": position,
    }
    return context, warnings


async def build_portfolio_review_context(
    req: PortfolioReviewRequest, portfolio_client: PortfolioClient
) -> tuple[dict, list[str]]:
    warnings: list[str] = []

    snapshot = await portfolio_client.get_snapshot()
    _note_if_unavailable("portfolio snapshot", snapshot, warnings)

    exposure = await portfolio_client.get_exposure()
    _note_if_unavailable("exposure breakdown", exposure, warnings)

    positions = None
    if req.include_positions:
        positions = await portfolio_client.get_positions()
        _note_if_unavailable("positions list", positions, warnings)

    context = {
        "snapshot": snapshot,
        "exposure": exposure,
        "positions": positions,
    }
    return context, warnings


async def build_risk_explanation_context(
    req: RiskExplanationRequest, risk_client: RiskClient
) -> tuple[dict, list[str]]:
    warnings: list[str] = []

    if req.symbol:
        risk_snapshot = await risk_client.get_symbol_risk(req.symbol)
        _note_if_unavailable(f"risk snapshot for {req.symbol}", risk_snapshot, warnings)
    else:
        risk_snapshot = await risk_client.get_risk_snapshot()
        _note_if_unavailable("portfolio-level risk snapshot", risk_snapshot, warnings)

    recent_events = await risk_client.get_recent_risk_events(limit=20)
    _note_if_unavailable("recent risk events", recent_events, warnings)

    context = {
        "requested_symbol": req.symbol,
        "risk_snapshot": risk_snapshot,
        "recent_risk_events": recent_events,
    }
    return context, warnings


async def build_market_summary_context(
    req: MarketSummaryRequest, market_data_client: MarketDataClient
) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    per_symbol: dict[str, dict] = {}

    for symbol in req.symbols:
        ltp = await market_data_client.get_ltp(symbol)
        _note_if_unavailable(f"LTP for {symbol}", ltp, warnings)

        history = await market_data_client.get_recent_history(symbol, days=5)
        _note_if_unavailable(f"recent history for {symbol}", history, warnings)

        per_symbol[symbol] = {"ltp": ltp, "recent_history": history}

    context = {"symbols": req.symbols, "per_symbol": per_symbol}
    return context, warnings


async def build_performance_explanation_context(
    req: PerformanceExplanationRequest, portfolio_client: PortfolioClient
) -> tuple[dict, list[str]]:
    warnings: list[str] = []

    performance = await portfolio_client.get_performance(req.window)
    _note_if_unavailable(f"performance for window {req.window}", performance, warnings)

    snapshot = await portfolio_client.get_snapshot()
    _note_if_unavailable("portfolio snapshot", snapshot, warnings)

    context = {
        "window": req.window,
        "performance": performance,
        "portfolio_snapshot": snapshot,
    }
    return context, warnings
