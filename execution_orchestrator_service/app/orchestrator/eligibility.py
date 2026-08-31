"""
Eligibility Engine — individual trade eligibility checks.

Each check is a pure async function receiving the full context
and returning an EligibilityResult(passed, check_name, reason, detail).

The pipeline runs ALL checks and aggregates results so the audit log
captures every check, not just the first failure.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.domain import (
    AggregatedSignal,
    EligibilityResult,
    PortfolioState,
    RejectionReason,
    RiskState,
    TradeAction,
)

settings = get_settings()
log = get_logger(__name__)


# ── 1. Confidence check ───────────────────────────────────────────────────────


async def check_confidence(signal: AggregatedSignal) -> EligibilityResult:
    passed = signal.confidence >= settings.MIN_CONFIDENCE
    return EligibilityResult(
        check_name="confidence",
        passed=passed,
        reason=RejectionReason.LOW_CONFIDENCE if not passed else None,
        detail=(
            f"confidence={signal.confidence:.3f} < threshold={settings.MIN_CONFIDENCE}"
            if not passed
            else None
        ),
    )


# ── 2. Liquidity check ────────────────────────────────────────────────────────


async def check_liquidity(
    signal: AggregatedSignal,
    portfolio: PortfolioState,
) -> EligibilityResult:
    """
    Ensure the portfolio has enough notional to make the trade meaningful.
    Proxy: available cash must meet the minimum liquidity threshold.
    """
    available = portfolio.cash_inr
    passed = available >= settings.MIN_LIQUIDITY_VALUE_INR
    return EligibilityResult(
        check_name="liquidity",
        passed=passed,
        reason=RejectionReason.LIQUIDITY_VIOLATION if not passed else None,
        detail=(
            f"cash={available:.0f} INR < min_liquidity={settings.MIN_LIQUIDITY_VALUE_INR:.0f} INR"
            if not passed
            else None
        ),
    )


# ── 3. Position limit check ───────────────────────────────────────────────────


async def check_position_limit(
    signal: AggregatedSignal,
    portfolio: PortfolioState,
) -> EligibilityResult:
    """
    Reject if the symbol already occupies MAX_POSITION_PCT of the portfolio.
    Applies only to BUY signals (we don't block additional SELL of existing pos).
    """
    if signal.final_signal != TradeAction.BUY:
        return EligibilityResult(check_name="position_limit", passed=True)

    position = portfolio.position_for(signal.symbol)
    if position is None:
        return EligibilityResult(check_name="position_limit", passed=True)

    current_pct = position.weight_pct
    passed = current_pct < settings.MAX_POSITION_PCT
    return EligibilityResult(
        check_name="position_limit",
        passed=passed,
        reason=RejectionReason.POSITION_LIMIT if not passed else None,
        detail=(
            f"{signal.symbol} already at {current_pct*100:.1f}% "
            f"(max {settings.MAX_POSITION_PCT*100:.1f}%)"
            if not passed
            else None
        ),
    )


# ── 4. Sector exposure check ──────────────────────────────────────────────────


async def check_sector_exposure(
    signal: AggregatedSignal,
    portfolio: PortfolioState,
) -> EligibilityResult:
    if signal.final_signal != TradeAction.BUY:
        return EligibilityResult(check_name="sector_exposure", passed=True)

    position = portfolio.position_for(signal.symbol)
    sector = position.sector if position else None
    if not sector:
        return EligibilityResult(check_name="sector_exposure", passed=True)

    sector_pct = portfolio.sector_exposure_pct(sector)
    passed = sector_pct < settings.MAX_SECTOR_EXPOSURE_PCT
    return EligibilityResult(
        check_name="sector_exposure",
        passed=passed,
        reason=RejectionReason.EXCESS_EXPOSURE if not passed else None,
        detail=(
            f"Sector '{sector}' at {sector_pct*100:.1f}% "
            f"(max {settings.MAX_SECTOR_EXPOSURE_PCT*100:.1f}%)"
            if not passed
            else None
        ),
    )


# ── 5. Correlation check ──────────────────────────────────────────────────────


async def check_correlation(
    signal: AggregatedSignal,
    risk: RiskState,
    portfolio: PortfolioState,
) -> EligibilityResult:
    """
    Reject if the incoming symbol is highly correlated (ρ > threshold)
    with any existing large position (> 5% weight).
    """
    if signal.final_signal != TradeAction.BUY:
        return EligibilityResult(check_name="correlation", passed=True)

    matrix = risk.correlation_matrix
    if not matrix or signal.symbol not in matrix:
        return EligibilityResult(check_name="correlation", passed=True)

    symbol_row = matrix[signal.symbol]
    large_positions = {
        p.symbol
        for p in portfolio.positions
        if p.weight_pct > 0.05 and p.symbol != signal.symbol
    }

    violators = [
        (sym, corr)
        for sym, corr in symbol_row.items()
        if sym in large_positions and abs(corr) > settings.MAX_CORRELATION_SCORE
    ]

    passed = len(violators) == 0
    return EligibilityResult(
        check_name="correlation",
        passed=passed,
        reason=RejectionReason.CORRELATION_VIOLATION if not passed else None,
        detail=(
            f"{signal.symbol} correlated with: "
            + ", ".join(f"{s}(ρ={c:.2f})" for s, c in violators)
            if not passed
            else None
        ),
    )


# ── 6. Daily loss limit check ─────────────────────────────────────────────────


async def check_daily_loss(risk: RiskState) -> EligibilityResult:
    if risk.kill_switch_active:
        return EligibilityResult(
            check_name="daily_loss",
            passed=False,
            reason=RejectionReason.DAILY_LOSS_LIMIT,
            detail="Kill switch is active — all new intents blocked",
        )

    passed = risk.daily_loss_inr < risk.daily_loss_limit_inr
    return EligibilityResult(
        check_name="daily_loss",
        passed=passed,
        reason=RejectionReason.DAILY_LOSS_LIMIT if not passed else None,
        detail=(
            f"daily_loss={risk.daily_loss_inr:.0f} INR "
            f">= limit={risk.daily_loss_limit_inr:.0f} INR"
            if not passed
            else None
        ),
    )


# ── 7. Portfolio drawdown check ───────────────────────────────────────────────


async def check_drawdown(risk: RiskState) -> EligibilityResult:
    passed = risk.drawdown_pct < risk.max_drawdown_pct
    return EligibilityResult(
        check_name="drawdown",
        passed=passed,
        reason=RejectionReason.DRAWDOWN_LIMIT if not passed else None,
        detail=(
            f"drawdown={risk.drawdown_pct*100:.2f}% "
            f">= max={risk.max_drawdown_pct*100:.2f}%"
            if not passed
            else None
        ),
    )


# ── 8. Open intents cap ───────────────────────────────────────────────────────


async def check_open_intents(risk: RiskState) -> EligibilityResult:
    passed = risk.open_intents_count < settings.MAX_OPEN_INTENTS
    return EligibilityResult(
        check_name="open_intents",
        passed=passed,
        reason=RejectionReason.MAX_OPEN_INTENTS if not passed else None,
        detail=(
            f"open_intents={risk.open_intents_count} >= max={settings.MAX_OPEN_INTENTS}"
            if not passed
            else None
        ),
    )


# ── Pipeline runner ───────────────────────────────────────────────────────────


async def run_all_checks(
    signal: AggregatedSignal,
    portfolio: PortfolioState,
    risk: RiskState,
) -> list[EligibilityResult]:
    """
    Run all eligibility checks and return results for every check.
    Does NOT short-circuit — all checks run for complete audit coverage.
    """
    results: list[EligibilityResult] = []

    results.append(await check_confidence(signal))
    results.append(await check_liquidity(signal, portfolio))
    results.append(await check_position_limit(signal, portfolio))
    results.append(await check_sector_exposure(signal, portfolio))
    results.append(await check_correlation(signal, risk, portfolio))
    results.append(await check_daily_loss(risk))
    results.append(await check_drawdown(risk))
    results.append(await check_open_intents(risk))

    failed = [r for r in results if not r.passed]
    if failed:
        log.info(
            "eligibility_checks_failed",
            symbol=signal.symbol,
            confidence=signal.confidence,
            failed_checks=[r.check_name for r in failed],
            reasons=[r.reason.value if r.reason else None for r in failed],
        )

    return results
