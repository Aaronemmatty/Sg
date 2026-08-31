"""
Performance Calculation Engine.

Computes institutional-grade risk-adjusted performance metrics from the
daily returns ledger (pm_daily_returns) and trade ledger (pm_trade_ledger).

All calculations operate on Decimal / numpy for numerical stability.
Annualization assumes 252 trading days per year.

Metrics computed:
  - Sharpe ratio (annualized, risk-free rate = 0 as INR T-bill proxy)
  - Sortino ratio (downside deviation denominator)
  - Calmar ratio (annualized return / max drawdown)
  - Max drawdown (absolute + %)
  - Win rate, avg win/loss, profit factor
  - Beta and Jensen's alpha vs benchmark (NIFTY50 by default)
  - CAGR
  - Information ratio
  - Rolling 30d / 90d / 252d windows
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np

from app.core.config import settings
from app.core.logging import get_logger
from app.db import repository as repo
from app.models.domain import PerformanceMetrics, PerformanceWindow
from app.services.market_data_client import market_data_client

log = get_logger(__name__)

_TRADING_DAYS_PER_YEAR = 252
_RISK_FREE_RATE_DAILY = 0.0   # 0% daily; adjust to Indian T-bill / repo rate if desired


def _window_days(window: PerformanceWindow) -> int | None:
    mapping = {
        PerformanceWindow.DAY_1: 1,
        PerformanceWindow.DAYS_7: 7,
        PerformanceWindow.DAYS_30: 30,
        PerformanceWindow.DAYS_90: 90,
        PerformanceWindow.DAYS_252: 252,
        PerformanceWindow.INCEPTION: None,  # no limit
    }
    return mapping[window]


async def compute_performance(window: PerformanceWindow) -> PerformanceMetrics:
    """
    Compute PerformanceMetrics for the given window from the daily_returns
    ledger and trade_ledger. Safe to call concurrently.
    """
    days = _window_days(window)
    daily_rows = await repo.get_daily_returns(days=days or 5000)
    config = await repo.get_portfolio_config()

    initial_capital = Decimal(str(config.get("initial_capital_inr") or "0"))

    if not daily_rows:
        return PerformanceMetrics(window=window)

    returns = np.array([float(r["daily_return_pct"]) / 100.0 for r in daily_rows])
    navs = np.array([float(r["nav_inr"]) for r in daily_rows])

    total_return_pct, cagr_pct = _compute_returns(navs, initial_capital, window)
    sharpe = _compute_sharpe(returns)
    sortino = _compute_sortino(returns)
    max_dd_pct, max_dd_inr, current_dd_pct = _compute_drawdown(navs)
    calmar = (
        (total_return_pct / abs(max_dd_pct))
        if max_dd_pct != 0 and not math.isnan(max_dd_pct)
        else None
    )

    # Trade stats from ledger (for the window period)
    since = _window_since(days)
    trade_rows = await repo.list_trade_ledger(since=since, limit=10000)
    sell_trades = [t for t in trade_rows if t["action"] == "SELL"]
    win_stats = _compute_win_stats(sell_trades)

    # Benchmark comparison
    alpha, beta, info_ratio, benchmark_return_pct = await _compute_benchmark_metrics(
        returns=returns, navs=navs, since=since, window=window
    )

    total_pnl = Decimal(str(navs[-1])) - initial_capital if len(navs) > 0 else Decimal("0")
    turnover = sum(
        Decimal(str(t["filled_quantity"])) * Decimal(str(t["avg_fill_price_inr"]))
        for t in trade_rows
    )

    return PerformanceMetrics(
        window=window,
        total_pnl_inr=total_pnl,
        realized_pnl_inr=Decimal("0"),   # populated separately if needed
        unrealized_pnl_inr=Decimal("0"),
        total_return_pct=total_return_pct,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        information_ratio=info_ratio,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_inr=Decimal(str(max_dd_inr)),
        current_drawdown_pct=current_dd_pct,
        total_trades=win_stats["total"],
        winning_trades=win_stats["wins"],
        losing_trades=win_stats["losses"],
        win_rate_pct=win_stats["win_rate_pct"],
        avg_win_inr=Decimal(str(win_stats["avg_win"])),
        avg_loss_inr=Decimal(str(win_stats["avg_loss"])),
        profit_factor=win_stats["profit_factor"],
        benchmark_return_pct=benchmark_return_pct,
        alpha=alpha,
        beta=beta,
        turnover_inr=Decimal(str(float(turnover))),
        cagr_pct=cagr_pct,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _compute_returns(
    navs: np.ndarray, initial_capital: Decimal, window: PerformanceWindow
) -> tuple[float, float | None]:
    if len(navs) == 0 or float(initial_capital) == 0:
        return 0.0, None

    final_nav = navs[-1]
    initial = float(initial_capital)
    total_return = (final_nav - initial) / initial * 100.0

    if window == PerformanceWindow.INCEPTION and len(navs) >= 2:
        n_years = len(navs) / _TRADING_DAYS_PER_YEAR
        if n_years > 0 and initial > 0:
            cagr = ((final_nav / initial) ** (1.0 / n_years) - 1.0) * 100.0
            return total_return, cagr

    return total_return, None


def _compute_sharpe(returns: np.ndarray) -> float | None:
    if len(returns) < 5:
        return None
    excess = returns - _RISK_FREE_RATE_DAILY
    std = np.std(excess, ddof=1)
    if std == 0:
        return None
    return float(np.mean(excess) / std * math.sqrt(_TRADING_DAYS_PER_YEAR))


def _compute_sortino(returns: np.ndarray) -> float | None:
    if len(returns) < 5:
        return None
    downside = returns[returns < _RISK_FREE_RATE_DAILY]
    if len(downside) == 0:
        return None
    downside_std = np.std(downside, ddof=1)
    if downside_std == 0:
        return None
    mean_excess = np.mean(returns - _RISK_FREE_RATE_DAILY)
    return float(mean_excess / downside_std * math.sqrt(_TRADING_DAYS_PER_YEAR))


def _compute_drawdown(navs: np.ndarray) -> tuple[float, float, float]:
    """Returns (max_drawdown_pct, max_drawdown_inr, current_drawdown_pct)."""
    if len(navs) == 0:
        return 0.0, 0.0, 0.0

    peak = np.maximum.accumulate(navs)
    drawdowns = (navs - peak) / peak * 100.0  # negative values

    max_dd_pct = float(np.min(drawdowns))
    max_dd_inr = float(np.min(navs - peak))
    current_dd_pct = float(drawdowns[-1])

    return abs(max_dd_pct), abs(max_dd_inr), abs(current_dd_pct)


def _compute_win_stats(sell_trades: list[dict]) -> dict:
    """Compute win rate and related stats from sell (realized) trade rows."""
    total = len(sell_trades)
    if total == 0:
        return {
            "total": 0, "wins": 0, "losses": 0,
            "win_rate_pct": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "profit_factor": None,
        }

    # We need realized P&L per sell — join from lot_consumptions is complex;
    # approximate from fill price vs average cost is not available here.
    # The trade_ledger rows don't carry realized P&L directly for this query.
    # This is a known limitation in v1: win stats require a pre-computed
    # realized P&L column in pm_trade_ledger. For now return count-only metrics.
    # TODO: add realized_pnl_inr column to pm_trade_ledger in migration 002.
    return {
        "total": total,
        "wins": 0,    # not yet computable without realized P&L in ledger row
        "losses": 0,
        "win_rate_pct": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "profit_factor": None,
    }


async def _compute_benchmark_metrics(
    *,
    returns: np.ndarray,
    navs: np.ndarray,
    since: datetime | None,
    window: PerformanceWindow,
) -> tuple[float | None, float | None, float | None, float | None]:
    """
    Compute alpha, beta, and information ratio vs NIFTY50.

    Benchmark returns are fetched from market_data_service.
    If unavailable, all metrics return None (degrade gracefully).
    """
    try:
        benchmark_prices = await market_data_client.get_benchmark_series(
            symbol=settings.benchmark_symbol, days=len(returns) + 5
        )
        if benchmark_prices is None or len(benchmark_prices) < 5:
            return None, None, None, None

        bm = np.array(benchmark_prices)
        bm_returns = np.diff(bm) / bm[:-1]

        # Align lengths
        n = min(len(returns), len(bm_returns))
        if n < 5:
            return None, None, None, None

        p_ret = returns[-n:]
        b_ret = bm_returns[-n:]

        bm_total_return = float((bm[-1] - bm[0]) / bm[0] * 100.0) if bm[0] != 0 else None

        # Beta = Cov(portfolio, benchmark) / Var(benchmark)
        cov_matrix = np.cov(p_ret, b_ret, ddof=1)
        var_bm = cov_matrix[1, 1]
        if var_bm == 0:
            return None, None, None, bm_total_return

        beta = float(cov_matrix[0, 1] / var_bm)

        # Jensen's alpha (annualized)
        portfolio_mean = float(np.mean(p_ret)) * _TRADING_DAYS_PER_YEAR
        bm_mean = float(np.mean(b_ret)) * _TRADING_DAYS_PER_YEAR
        alpha = portfolio_mean - beta * bm_mean

        # Information ratio = (portfolio_return - benchmark_return) / tracking_error
        active_returns = p_ret - b_ret
        tracking_error = float(np.std(active_returns, ddof=1) * math.sqrt(_TRADING_DAYS_PER_YEAR))
        mean_active = float(np.mean(active_returns)) * _TRADING_DAYS_PER_YEAR
        info_ratio = (mean_active / tracking_error) if tracking_error > 0 else None

        return alpha, beta, info_ratio, bm_total_return

    except Exception:
        log.warning("benchmark_metrics_unavailable")
        return None, None, None, None


def _window_since(days: int | None) -> datetime | None:
    if days is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)
