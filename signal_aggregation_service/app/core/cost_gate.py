"""
Pre-trade Transaction Cost Gate.

Models round-trip transaction costs for Indian retail equity intraday trading:
  - Commission: Zerodha flat ₹20 or 0.03% (whichever is lower) per executed leg,
    derived from commission_bps (3 bps default, matching backtesting_engine_service).
  - Slippage: 5 bps per leg (round-trip: 10 bps total).
  - STT (Securities Transaction Tax): 0.025% on sell leg only.
  - Exchange transaction charges: 0.00345% on turnover (both buy and sell legs).
  - Stamp duty: 0.015% on buy leg only.
  - GST: 18% on (brokerage + exchange transaction charges).

Evaluates whether the strategy's expected move exceeds the round-trip friction
hurdle by a required margin (cost must be <= 33.33% of expected gross move,
meaning expected move must be at least 3x the friction cost).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from app.config import Settings
from app.models.domain import SignalAction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransactionCostEstimate:
    notional_inr: float
    brokerage_inr: float
    slippage_inr: float
    stt_inr: float
    exchange_txn_inr: float
    stamp_duty_inr: float
    gst_inr: float
    total_round_trip_cost_inr: float
    round_trip_cost_pct: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def estimate_round_trip_cost(notional_inr: float, settings: Settings) -> TransactionCostEstimate:
    """
    Computes round-trip transaction costs (entry + exit legs) for Indian retail equity
    at the specified position notional value.
    """
    notional = max(float(notional_inr), 1.0)

    # 1. Brokerage (Zerodha intraday: 0.03% or flat ₹20, whichever is lower per leg)
    leg_pct = settings.COST_GATE_COMMISSION_BPS / 10_000.0  # 3 bps = 0.0003
    brokerage_per_leg = min(20.0, notional * leg_pct)
    total_brokerage = round(2.0 * brokerage_per_leg, 4)

    # 2. Slippage (applied on both entry and exit legs)
    slippage_per_leg = notional * (settings.COST_GATE_SLIPPAGE_BPS / 10_000.0)
    total_slippage = round(2.0 * slippage_per_leg, 4)

    # 3. STT (Securities Transaction Tax: 0.025% on sell side only)
    stt = round(notional * settings.COST_GATE_STT_RATE, 4)

    # 4. Exchange transaction charges (0.00345% turnover on both legs)
    exchange_txn = round(2.0 * notional * settings.COST_GATE_EXCHANGE_TXN_RATE, 4)

    # 5. Stamp duty (0.015% buy side only)
    stamp_duty = round(notional * settings.COST_GATE_STAMP_DUTY_RATE, 4)

    # 6. GST (18% on brokerage + exchange transaction charges)
    gst = round(settings.COST_GATE_GST_RATE * (total_brokerage + exchange_txn), 4)

    total_cost = round(
        total_brokerage + total_slippage + stt + exchange_txn + stamp_duty + gst, 4
    )
    cost_pct = round(total_cost / notional, 6)

    return TransactionCostEstimate(
        notional_inr=notional,
        brokerage_inr=total_brokerage,
        slippage_inr=total_slippage,
        stt_inr=stt,
        exchange_txn_inr=exchange_txn,
        stamp_duty_inr=stamp_duty,
        gst_inr=gst,
        total_round_trip_cost_inr=total_cost,
        round_trip_cost_pct=cost_pct,
    )


@dataclass
class CostGateDecision:
    passed: bool
    suppressed: bool
    expected_move_pct: float
    expected_move_inr: float
    round_trip_cost_inr: float
    round_trip_cost_pct: float
    cost_to_move_ratio: float
    hurdle_ratio: float
    position_size_inr: float
    reason: str
    cost_estimate: TransactionCostEstimate

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "suppressed": self.suppressed,
            "expected_move_pct": round(self.expected_move_pct, 6),
            "expected_move_inr": round(self.expected_move_inr, 4),
            "round_trip_cost_inr": round(self.round_trip_cost_inr, 4),
            "round_trip_cost_pct": round(self.round_trip_cost_pct, 6),
            "cost_to_move_ratio": round(self.cost_to_move_ratio, 4),
            "hurdle_ratio": round(self.hurdle_ratio, 4),
            "position_size_inr": round(self.position_size_inr, 2),
            "reason": self.reason,
            "cost_breakdown": self.cost_estimate.to_dict(),
        }


def extract_expected_move(
    raw_signals: dict[str, dict],
    contributors: list[str],
    default_move_pct: float = 0.02,
) -> float:
    """
    Extracts the expected percentage move from contributing strategy signals.
    Inspects:
      - 'expected_move', 'expected_return', 'target_pct', 'expected_move_pct'
      - metadata dictionary containing the above keys
      - (take_profit - entry_price) / entry_price if both are provided.

    If multiple contributing strategies specify expected moves, computes their average.
    If none specify an expected move, returns `default_move_pct`.
    """
    moves: list[float] = []

    strategies_to_check = [s for s in contributors if s in raw_signals] or list(raw_signals.keys())

    for strat in strategies_to_check:
        raw = raw_signals.get(strat) or {}
        val = None

        for k in ("expected_move_pct", "expected_move", "expected_return", "target_pct"):
            if k in raw and raw[k] is not None:
                val = float(raw[k])
                break

        if val is None and isinstance(raw.get("metadata"), dict):
            meta = raw["metadata"]
            for k in ("expected_move_pct", "expected_move", "expected_return", "target_pct"):
                if k in meta and meta[k] is not None:
                    val = float(meta[k])
                    break

        if val is None:
            entry = raw.get("entry_price")
            tp = raw.get("take_profit")
            if entry and tp and float(entry) > 0:
                val = abs(float(tp) - float(entry)) / float(entry)

        if val is not None and val > 0:
            # If specified as percentage > 0.5 (e.g. 1.5 meaning 1.5%), convert to decimal
            if val > 0.5:
                val = val / 100.0
            moves.append(val)

    if moves:
        return sum(moves) / len(moves)
    return default_move_pct


class CostGateEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate(
        self,
        symbol: str,
        final_signal: SignalAction,
        raw_signals: dict[str, dict],
        contributors: list[str],
        live_cash: float | None = None,
    ) -> CostGateDecision:
        """
        Evaluates the pre-trade cost gate for a signal.
        For non-directional signals (HOLD) or when the gate is disabled, passes immediately.
        For BUY/SELL, verifies expected_move exceeds round-trip friction by the hurdle ratio.
        """
        # 1. Position sizing (20% allocation of retail capital ~ ₹1,800)
        cash = live_cash if (live_cash is not None and live_cash > 0) else self.settings.COST_GATE_ACCOUNT_CAPITAL_INR
        position_size_inr = cash * self.settings.COST_GATE_POSITION_SIZE_PCT

        cost_estimate = estimate_round_trip_cost(position_size_inr, self.settings)

        # 2. Gate disabled or HOLD signal -> pass without suppression
        if not self.settings.COST_GATE_ENABLED or final_signal == SignalAction.HOLD:
            return CostGateDecision(
                passed=True,
                suppressed=False,
                expected_move_pct=0.0,
                expected_move_inr=0.0,
                round_trip_cost_inr=cost_estimate.total_round_trip_cost_inr,
                round_trip_cost_pct=cost_estimate.round_trip_cost_pct,
                cost_to_move_ratio=0.0,
                hurdle_ratio=self.settings.COST_GATE_MAX_COST_TO_MOVE_RATIO,
                position_size_inr=position_size_inr,
                reason="HOLD or cost gate disabled; no execution required",
                cost_estimate=cost_estimate,
            )

        # 3. Resolve strategy's expected move
        expected_move_pct = extract_expected_move(
            raw_signals, contributors, self.settings.COST_GATE_DEFAULT_EXPECTED_MOVE_PCT
        )
        expected_move_inr = position_size_inr * expected_move_pct

        # 4. Hurdle computation
        if expected_move_inr <= 0:
            cost_to_move_ratio = float("inf")
        else:
            cost_to_move_ratio = cost_estimate.total_round_trip_cost_inr / expected_move_inr

        hurdle = self.settings.COST_GATE_MAX_COST_TO_MOVE_RATIO
        passed = cost_to_move_ratio <= hurdle
        suppressed = not passed

        if passed:
            reason = (
                f"Expected move INR {expected_move_inr:.2f} ({expected_move_pct:.2%}) "
                f"clears round-trip cost INR {cost_estimate.total_round_trip_cost_inr:.2f} "
                f"({cost_estimate.round_trip_cost_pct:.2%}) with cost_ratio={cost_to_move_ratio:.1%} "
                f"<= max_hurdle={hurdle:.1%}"
            )
        else:
            reason = (
                f"Friction too high: round-trip cost INR {cost_estimate.total_round_trip_cost_inr:.2f} "
                f"({cost_estimate.round_trip_cost_pct:.2%}) is {cost_to_move_ratio:.1%} of expected move "
                f"INR {expected_move_inr:.2f} ({expected_move_pct:.2%}), exceeding max_hurdle={hurdle:.1%}"
            )
            logger.warning(
                "COST_GATE_REJECTED: symbol=%s action=%s expected_move=INR %.2f (%.4f) "
                "round_trip_cost=INR %.2f (%.4f) cost_ratio=%.2f%% > hurdle=%.2f%%",
                symbol,
                final_signal.value,
                expected_move_inr,
                expected_move_pct,
                cost_estimate.total_round_trip_cost_inr,
                cost_estimate.round_trip_cost_pct,
                cost_to_move_ratio * 100,
                hurdle * 100,
            )

        return CostGateDecision(
            passed=passed,
            suppressed=suppressed,
            expected_move_pct=expected_move_pct,
            expected_move_inr=expected_move_inr,
            round_trip_cost_inr=cost_estimate.total_round_trip_cost_inr,
            round_trip_cost_pct=cost_estimate.round_trip_cost_pct,
            cost_to_move_ratio=cost_to_move_ratio,
            hurdle_ratio=hurdle,
            position_size_inr=position_size_inr,
            reason=reason,
            cost_estimate=cost_estimate,
        )
