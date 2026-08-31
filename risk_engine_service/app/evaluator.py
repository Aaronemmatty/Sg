from __future__ import annotations

import time
import uuid
from typing import Any

from app.circuit_breaker import CircuitBreakerRegistry
from app.clients import BrokerServiceClient, MarketDataClient, PortfolioClient
from app.config import Settings
from app.kill_switch import KillSwitch
from app.logging_setup import get_logger
from app.metrics import (
    EVALUATION_LATENCY,
    INTENTS_EVALUATED,
    REJECTION_REASONS,
    RISK_SCORE_GAUGE,
    VAR_BREACH_TOTAL,
)
from app.models import (
    CheckResult,
    RiskBand,
    RiskDecision,
    RiskRejectionReason,
    RiskStatus,
    TradeIntent,
)
from app.policies import (
    check_circuit_breaker,
    check_concentration,
    check_correlation,
    check_daily_loss,
    check_drawdown,
    check_margin,
    check_position_sizing,
    check_sector_exposure,
    check_var,
    check_volatility,
)
from app.repository import Database
from app.scoring import compute_risk_score

log = get_logger(module="evaluator")

# Placeholder sector mapping. In production this should be sourced from a
# shared reference-data table / market_data_service rather than hardcoded;
# left as an explicit extension point.
SECTOR_MAP: dict[str, str] = {}


class RiskEvaluator:
    def __init__(
        self,
        db: Database,
        broker_client: BrokerServiceClient,
        market_data_client: MarketDataClient,
        portfolio_client: PortfolioClient,
        kill_switch: KillSwitch,
        circuit_breakers: CircuitBreakerRegistry,
        settings: Settings,
    ) -> None:
        self._db = db
        self._broker = broker_client
        self._market_data = market_data_client
        self._portfolio = portfolio_client
        self._kill_switch = kill_switch
        self._circuit_breakers = circuit_breakers
        self._settings = settings
        self._policy_cache: dict[str, dict[str, Any]] = {}
        self._policy_cache_ts: float = 0.0

    async def _get_policies(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        if now - self._policy_cache_ts > 15.0 or not self._policy_cache:
            rows = await self._db.get_all_policies()
            self._policy_cache = {r["policy_name"]: r for r in rows}
            self._policy_cache_ts = now
        return self._policy_cache

    def _policy_params(self, policies: dict[str, dict[str, Any]], name: str) -> tuple[bool, dict[str, Any]]:
        p = policies.get(name)
        if p is None:
            return True, {}
        return bool(p.get("enabled", True)), dict(p.get("params", {}))

    async def evaluate(self, intent: TradeIntent) -> RiskDecision:
        start = time.perf_counter()
        policies = await self._get_policies()
        checks: dict[str, CheckResult] = {}
        rejection_reasons: list[RiskRejectionReason] = []

        # --- 0. Global kill switch ---------------------------------------
        kill_switch_active = self._kill_switch.state.is_halted
        if kill_switch_active:
            rejection_reasons.append(RiskRejectionReason.KILL_SWITCH_ACTIVE)

        # --- 0b. Symbol-level circuit breaker (pre-existing trip) --------
        already_tripped = await self._circuit_breakers.is_tripped(intent.symbol)

        # --- Gather portfolio + market context ----------------------------
        portfolio = await self._portfolio.get_portfolio_snapshot()
        vol_enabled, vol_params = self._policy_params(policies, "volatility_limit")
        annualized_vol = await self._market_data.get_volatility(intent.symbol) if vol_enabled else None

        intraday_move = None
        if vol_enabled:
            intraday_move = await self._market_data.get_intraday_move_percent(
                intent.symbol, vol_params.get("circuit_breaker_window_minutes", 5)
            )

        open_symbols = list(portfolio.open_positions.keys())
        corr_enabled, corr_params = self._policy_params(policies, "correlation_limit")
        correlation_matrix = None
        if corr_enabled and open_symbols:
            correlation_matrix = await self._market_data.get_correlation_matrix(
                list(set(open_symbols + [intent.symbol])), corr_params.get("lookback_days", 60)
            )

        # --- 1. Position sizing (may reduce allocation) -------------------
        sizing_enabled, sizing_params = self._policy_params(policies, "position_sizing")
        working_allocation = intent.allocation_inr
        if sizing_enabled:
            sizing_result, working_allocation = check_position_sizing(
                allocation_inr=intent.allocation_inr, nav_inr=portfolio.nav_inr, params=sizing_params
            )
            checks["position_sizing"] = sizing_result
            if not sizing_result.passed:
                rejection_reasons.append(RiskRejectionReason.POSITION_SIZING_VIOLATION)

        # --- 2. VaR --------------------------------------------------------
        var_enabled, var_params = self._policy_params(policies, "var_limit")
        var_inr = None
        var_pct = None
        if var_enabled:
            var_result, var_inr, var_pct = check_var(
                allocation_inr=working_allocation,
                annualized_vol_percent=annualized_vol,
                nav_inr=portfolio.nav_inr,
                params=var_params,
            )
            checks["var"] = var_result
            if not var_result.passed:
                rejection_reasons.append(RiskRejectionReason.VAR_BREACH)
                VAR_BREACH_TOTAL.labels(symbol=intent.symbol).inc()

        # --- 3. Drawdown -----------------------------------------------------
        dd_enabled, dd_params = self._policy_params(policies, "drawdown_limit")
        if dd_enabled:
            dd_result = check_drawdown(portfolio=portfolio, params=dd_params)
            checks["drawdown"] = dd_result
            if not dd_result.passed:
                rejection_reasons.append(RiskRejectionReason.DRAWDOWN_LIMIT_BREACH)

        # --- 4. Daily loss ----------------------------------------------------
        daily_enabled, daily_params = self._policy_params(policies, "daily_loss_limit")
        if daily_enabled:
            daily_result = check_daily_loss(portfolio=portfolio, params=daily_params)
            checks["daily_loss"] = daily_result
            if not daily_result.passed:
                rejection_reasons.append(RiskRejectionReason.DAILY_LOSS_LIMIT_BREACH)

        # --- 5. Concentration --------------------------------------------------
        conc_enabled, conc_params = self._policy_params(policies, "concentration_limit")
        if conc_enabled:
            conc_result = check_concentration(
                symbol=intent.symbol, allocation_inr=working_allocation, portfolio=portfolio, params=conc_params
            )
            checks["concentration"] = conc_result
            if not conc_result.passed:
                rejection_reasons.append(RiskRejectionReason.CONCENTRATION_LIMIT)

        # --- 6. Sector exposure ---------------------------------------------------
        sector_enabled, sector_params = self._policy_params(policies, "sector_exposure_limit")
        if sector_enabled:
            sector_result = check_sector_exposure(
                sector=SECTOR_MAP.get(intent.symbol),
                allocation_inr=working_allocation,
                portfolio=portfolio,
                params=sector_params,
            )
            checks["sector_exposure"] = sector_result
            if not sector_result.passed:
                rejection_reasons.append(RiskRejectionReason.SECTOR_EXPOSURE_BREACH)

        # --- 7. Correlation -----------------------------------------------------------
        if corr_enabled:
            corr_result = check_correlation(
                symbol=intent.symbol,
                open_symbols=open_symbols,
                correlation_matrix=correlation_matrix,
                params=corr_params,
            )
            checks["correlation"] = corr_result
            if not corr_result.passed:
                rejection_reasons.append(RiskRejectionReason.CORRELATION_BREACH)

        # --- 8. Volatility + circuit breaker -------------------------------------------
        if vol_enabled:
            vol_result = check_volatility(annualized_vol_percent=annualized_vol, params=vol_params)
            checks["volatility"] = vol_result
            if not vol_result.passed:
                rejection_reasons.append(RiskRejectionReason.VOLATILITY_HALT)

            cb_result = check_circuit_breaker(intraday_move_percent=intraday_move, params=vol_params)
            checks["circuit_breaker"] = cb_result
            if not cb_result.passed:
                rejection_reasons.append(RiskRejectionReason.CIRCUIT_BREAKER_TRIPPED)
                await self._circuit_breakers.trip(
                    intent.symbol, "intraday_move_breach", intraday_move, cb_result.threshold
                )
            elif already_tripped:
                rejection_reasons.append(RiskRejectionReason.CIRCUIT_BREAKER_TRIPPED)
                checks["circuit_breaker"] = CheckResult(
                    passed=False, detail="Symbol circuit breaker already tripped (cool-down active)"
                )

        # --- 9. Margin -----------------------------------------------------------------
        margin_enabled, margin_params = self._policy_params(policies, "margin_check")
        if margin_enabled:
            margin_snapshot = await self._broker.get_margin_snapshot(fallback_nav_inr=portfolio.nav_inr)
            margin_result = check_margin(allocation_inr=working_allocation, margin_snapshot=margin_snapshot, params=margin_params)
            checks["margin"] = margin_result
            if not margin_result.passed:
                rejection_reasons.append(RiskRejectionReason.MARGIN_INSUFFICIENT)

        # --- 10. Composite score -------------------------------------------------------
        risk_score, risk_band = compute_risk_score(checks)
        RISK_SCORE_GAUGE.labels(symbol=intent.symbol).set(risk_score)

        score_enabled, score_params = self._policy_params(policies, "risk_score_threshold")
        reject_at = score_params.get("reject_at_or_above", 81) if score_enabled else 1000
        hold_band = score_params.get("hold_band", [61, 80]) if score_enabled else [1000, 1000]

        if risk_score >= reject_at:
            rejection_reasons.append(RiskRejectionReason.RISK_SCORE_TOO_HIGH)

        # --- Final status decision -------------------------------------------------------
        hard_reject = kill_switch_active or len([r for r in rejection_reasons if r != RiskRejectionReason.RISK_SCORE_TOO_HIGH]) > 0
        if hard_reject or risk_score >= reject_at:
            status_ = RiskStatus.RISK_REJECTED
            approved_allocation = None
        elif hold_band[0] <= risk_score <= hold_band[1]:
            status_ = RiskStatus.RISK_HOLD
            approved_allocation = working_allocation
        else:
            status_ = RiskStatus.RISK_APPROVED
            approved_allocation = working_allocation

        decision = RiskDecision(
            intent_id=intent.intent_id,
            symbol=intent.symbol,
            action=intent.action,
            original_allocation_inr=intent.allocation_inr,
            approved_allocation_inr=approved_allocation,
            risk_score=risk_score,
            risk_band=risk_band,
            var_inr=var_inr,
            var_percent_of_portfolio=var_pct,
            status=status_,
            rejection_reasons=list(dict.fromkeys(rejection_reasons)),  # dedupe, preserve order
            checks=checks,
            kill_switch_active=kill_switch_active,
            market_regime=intent.market_regime,
            correlation_id=intent.correlation_id,
        )

        elapsed = time.perf_counter() - start
        EVALUATION_LATENCY.observe(elapsed)
        INTENTS_EVALUATED.labels(symbol=intent.symbol, status=status_.value).inc()
        for r in decision.rejection_reasons:
            REJECTION_REASONS.labels(symbol=intent.symbol, reason=r.value).inc()

        log.info(
            "intent_evaluated",
            intent_id=str(intent.intent_id),
            symbol=intent.symbol,
            status=status_.value,
            risk_score=risk_score,
            risk_band=risk_band.value,
            elapsed_ms=round(elapsed * 1000, 2),
        )
        return decision
