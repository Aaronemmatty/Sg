from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.logging_setup import get_logger
from app.models import CheckResult, PortfolioSnapshot

log = get_logger(module="policies")

# z-scores for common one-tailed confidence levels used in parametric VaR
Z_SCORES = {0.90: 1.2816, 0.95: 1.6449, 0.975: 1.9600, 0.99: 2.3263}


def _z_for_confidence(confidence: float) -> float:
    return Z_SCORES.get(round(confidence, 3), 1.6449)


def calc_parametric_var_inr(
    allocation_inr: float, annualized_vol_percent: float, confidence: float, horizon_days: int
) -> float:
    """Parametric (variance-covariance) VaR.

    VaR = position_value * z * daily_vol * sqrt(horizon_days)

    Chosen as the default real-time method: it requires only a single
    volatility figure per symbol (already needed for the volatility
    policy) rather than a full historical return series, so it can run
    synchronously in the hot pre-trade path without an extra heavy
    fetch. The interface is intentionally narrow so a historical /
    Monte Carlo method can be substituted later without touching
    callers.
    """
    if annualized_vol_percent is None or annualized_vol_percent <= 0:
        # Unknown volatility -> cannot bound risk -> treat as maximally risky
        annualized_vol_percent = 100.0
    daily_vol = (annualized_vol_percent / 100.0) / math.sqrt(252)
    z = _z_for_confidence(confidence)
    var_fraction = z * daily_vol * math.sqrt(max(horizon_days, 1))
    return allocation_inr * var_fraction


def check_var(
    *, allocation_inr: float, annualized_vol_percent: float | None, nav_inr: float, params: dict[str, Any]
) -> tuple[CheckResult, float, float]:
    confidence = params.get("confidence", 0.95)
    horizon_days = params.get("horizon_days", 1)
    max_var_pct = params.get("max_var_percent_of_portfolio", 2.0)

    var_inr = calc_parametric_var_inr(allocation_inr, annualized_vol_percent or 100.0, confidence, horizon_days)
    var_pct_of_portfolio = (var_inr / nav_inr * 100.0) if nav_inr > 0 else 100.0

    passed = var_pct_of_portfolio <= max_var_pct
    detail = f"{horizon_days}d VaR@{int(confidence*100)}% = ₹{var_inr:,.0f} ({var_pct_of_portfolio:.2f}% of NAV)"
    return (
        CheckResult(passed=passed, detail=detail, value=var_pct_of_portfolio, threshold=max_var_pct),
        var_inr,
        var_pct_of_portfolio,
    )


def check_position_sizing(*, allocation_inr: float, nav_inr: float, params: dict[str, Any]) -> tuple[CheckResult, float]:
    """Hard bounds + possible downward override of allocation. Returns
    (result, risk_adjusted_allocation_inr)."""
    max_pct = params.get("max_allocation_per_intent_percent", 10.0)
    min_inr = params.get("min_allocation_inr", 500.0)

    max_allowed_inr = nav_inr * (max_pct / 100.0) if nav_inr > 0 else 0.0
    adjusted = min(allocation_inr, max_allowed_inr) if max_allowed_inr > 0 else allocation_inr

    if adjusted < min_inr:
        return (
            CheckResult(
                passed=False,
                detail=f"Allocation ₹{adjusted:,.0f} below minimum ₹{min_inr:,.0f}",
                value=adjusted,
                threshold=min_inr,
            ),
            adjusted,
        )

    capped = adjusted < allocation_inr
    detail = (
        f"Allocation capped from ₹{allocation_inr:,.0f} to ₹{adjusted:,.0f} (max {max_pct}% NAV)"
        if capped
        else f"Allocation ₹{adjusted:,.0f} within sizing bounds"
    )
    return CheckResult(passed=True, detail=detail, value=adjusted, threshold=max_allowed_inr), adjusted


def check_drawdown(*, portfolio: PortfolioSnapshot, params: dict[str, Any]) -> CheckResult:
    max_dd = params.get("max_drawdown_percent", 10.0)
    if portfolio.peak_equity_inr <= 0:
        return CheckResult(passed=True, detail="No peak equity recorded yet", value=0.0, threshold=max_dd)
    current_dd_pct = max(0.0, (portfolio.peak_equity_inr - portfolio.nav_inr) / portfolio.peak_equity_inr * 100.0)
    passed = current_dd_pct < max_dd
    return CheckResult(
        passed=passed,
        detail=f"Current drawdown {current_dd_pct:.2f}% (limit {max_dd}%)",
        value=current_dd_pct,
        threshold=max_dd,
    )


def check_daily_loss(*, portfolio: PortfolioSnapshot, params: dict[str, Any]) -> CheckResult:
    max_loss_pct = params.get("max_daily_loss_percent", 3.0)
    base = portfolio.daily_start_equity_inr
    if base <= 0:
        return CheckResult(passed=True, detail="No daily baseline equity recorded yet", value=0.0, threshold=max_loss_pct)
    loss_pct = max(0.0, -portfolio.daily_pnl_inr / base * 100.0)
    passed = loss_pct < max_loss_pct
    return CheckResult(
        passed=passed,
        detail=f"Daily loss {loss_pct:.2f}% of equity (limit {max_loss_pct}%)",
        value=loss_pct,
        threshold=max_loss_pct,
    )


def check_concentration(
    *, symbol: str, allocation_inr: float, portfolio: PortfolioSnapshot, params: dict[str, Any]
) -> CheckResult:
    max_pct = params.get("max_single_position_percent", 8.0)
    existing = portfolio.open_positions.get(symbol, {}).get("market_value_inr", 0.0)
    post_trade_value = existing + allocation_inr
    nav = portfolio.nav_inr if portfolio.nav_inr > 0 else (post_trade_value or 1.0)
    pct = post_trade_value / nav * 100.0
    passed = pct <= max_pct
    return CheckResult(
        passed=passed,
        detail=f"Post-trade {symbol} concentration {pct:.2f}% of NAV (limit {max_pct}%)",
        value=pct,
        threshold=max_pct,
    )


def check_sector_exposure(
    *, sector: str | None, allocation_inr: float, portfolio: PortfolioSnapshot, params: dict[str, Any]
) -> CheckResult:
    max_pct = params.get("max_sector_percent", 25.0)
    if not sector:
        return CheckResult(passed=True, detail="No sector mapping available, skipped", value=0.0, threshold=max_pct)
    existing = portfolio.sector_exposure_inr.get(sector, 0.0)
    post_trade_value = existing + allocation_inr
    nav = portfolio.nav_inr if portfolio.nav_inr > 0 else (post_trade_value or 1.0)
    pct = post_trade_value / nav * 100.0
    passed = pct <= max_pct
    return CheckResult(
        passed=passed,
        detail=f"Post-trade '{sector}' sector exposure {pct:.2f}% of NAV (limit {max_pct}%)",
        value=pct,
        threshold=max_pct,
    )


def check_correlation(
    *, symbol: str, open_symbols: list[str], correlation_matrix: dict[str, dict[str, float]] | None, params: dict[str, Any]
) -> CheckResult:
    max_avg_corr = params.get("max_avg_correlation", 0.75)
    others = [s for s in open_symbols if s != symbol]
    if not others or not correlation_matrix or symbol not in correlation_matrix:
        return CheckResult(passed=True, detail="No comparable open positions / data, skipped", value=0.0, threshold=max_avg_corr)

    row = correlation_matrix.get(symbol, {})
    values = [abs(row[o]) for o in others if o in row]
    if not values:
        return CheckResult(passed=True, detail="No correlation data vs open positions, skipped", value=0.0, threshold=max_avg_corr)

    avg_corr = float(np.mean(values))
    passed = avg_corr <= max_avg_corr
    return CheckResult(
        passed=passed,
        detail=f"Avg |correlation| vs {len(values)} open position(s) = {avg_corr:.2f} (limit {max_avg_corr})",
        value=avg_corr,
        threshold=max_avg_corr,
    )


def check_volatility(*, annualized_vol_percent: float | None, params: dict[str, Any]) -> CheckResult:
    max_vol = params.get("max_annualized_vol_percent", 80.0)
    if annualized_vol_percent is None:
        return CheckResult(passed=True, detail="Volatility data unavailable, skipped", value=None, threshold=max_vol)
    passed = annualized_vol_percent <= max_vol
    return CheckResult(
        passed=passed,
        detail=f"Annualized volatility {annualized_vol_percent:.1f}% (limit {max_vol}%)",
        value=annualized_vol_percent,
        threshold=max_vol,
    )


def check_circuit_breaker(*, intraday_move_percent: float | None, params: dict[str, Any]) -> CheckResult:
    threshold = params.get("circuit_breaker_intraday_move_percent", 7.0)
    window = params.get("circuit_breaker_window_minutes", 5)
    if intraday_move_percent is None:
        return CheckResult(passed=True, detail="Intraday move data unavailable, skipped", value=None, threshold=threshold)
    tripped = abs(intraday_move_percent) >= threshold
    return CheckResult(
        passed=not tripped,
        detail=f"{window}m move {intraday_move_percent:+.2f}% (breaker at ±{threshold}%)",
        value=intraday_move_percent,
        threshold=threshold,
    )


def check_margin(
    *, allocation_inr: float, margin_snapshot: dict[str, Any], params: dict[str, Any]
) -> CheckResult:
    buffer_pct = params.get("min_free_margin_buffer_percent", 15.0)
    free_margin = margin_snapshot.get("free_margin_inr", 0.0)
    total_margin = margin_snapshot.get("total_margin_inr", 0.0) or 1.0

    post_trade_free = free_margin - allocation_inr
    min_required_buffer = total_margin * (buffer_pct / 100.0)
    passed = post_trade_free >= min_required_buffer
    source = margin_snapshot.get("source", "unknown")
    return CheckResult(
        passed=passed,
        detail=(
            f"Post-trade free margin ₹{post_trade_free:,.0f} vs required buffer ₹{min_required_buffer:,.0f} "
            f"(source={source})"
        ),
        value=post_trade_free,
        threshold=min_required_buffer,
    )
