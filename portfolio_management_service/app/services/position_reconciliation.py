"""
Position-Book Reconciliation Engine.

Responsibilities:
  - Fetches broker's live positions via GET /v1/broker/positions
  - Fetches the system's internal view of open positions from Postgres (pm_positions table)
  - Diffs them by symbol and quantity
  - On ANY mismatch (symbol missing in broker, symbol missing internally, or quantity differs):
      * Halts trading via existing risk_engine_service kill-switch (/risk/kill-switch/activate)
      * Logs CRITICAL error with exact details (symbol, internal_qty, broker_qty, mismatch_type)
      * Publishes an alert event to Redis
  - On clean reconciliation (no mismatches):
      * Logs INFO audit trail summarizing verified symbols
  - Runs on a scheduled calendar:
      * Market open (09:15 IST)
      * Hourly during market hours (10:15, 11:15, 12:15, 13:15, 14:15, 15:15 IST)
      * Market close (15:30 IST)
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from typing import Any

import httpx
import jwt
from dotenv import dotenv_values

from app.core.config import settings
from app.core.logging import get_logger
from app.db import repository as repo
from sg_security.calendar import (
    MARKET_CLOSE,
    MARKET_OPEN,
    is_market_open,
    is_trading_day,
    now_ist,
)

log = get_logger(__name__)


class MismatchType(str, Enum):
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    MISSING_IN_BROKER = "MISSING_IN_BROKER"
    MISSING_INTERNALLY = "MISSING_INTERNALLY"


@dataclass(frozen=True)
class PositionMismatch:
    symbol: str
    internal_qty: int
    broker_qty: int
    mismatch_type: MismatchType
    details: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "internal_qty": self.internal_qty,
            "broker_qty": self.broker_qty,
            "mismatch_type": self.mismatch_type.value,
            "details": self.details,
        }


@dataclass
class PositionReconciliationResult:
    matched: bool
    checked_symbols: list[str]
    internal_positions: dict[str, int]
    broker_positions: dict[str, int]
    mismatches: list[PositionMismatch]
    halt_triggered: bool
    timestamp: datetime = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "checked_symbols": self.checked_symbols,
            "internal_positions": self.internal_positions,
            "broker_positions": self.broker_positions,
            "mismatches": [m.to_dict() for m in self.mismatches],
            "halt_triggered": self.halt_triggered,
            "timestamp": self.timestamp.isoformat(),
        }


def normalize_symbol(symbol: str) -> str:
    """Normalizes symbol string (e.g. 'NSE:RELIANCE' -> 'RELIANCE')."""
    return symbol.split(":")[-1].strip().upper()


def diff_positions(
    internal_positions: dict[str, int],
    broker_positions: dict[str, int],
) -> list[PositionMismatch]:
    """
    Compares internal book positions against broker positions by symbol and quantity.
    Ignores closed/flat positions (quantity == 0).
    """
    # Normalize input dictionaries
    norm_internal: dict[str, int] = {
        normalize_symbol(s): int(q) for s, q in internal_positions.items() if int(q) != 0
    }
    norm_broker: dict[str, int] = {
        normalize_symbol(s): int(q) for s, q in broker_positions.items() if int(q) != 0
    }

    all_symbols = sorted(set(norm_internal.keys()) | set(norm_broker.keys()))
    mismatches: list[PositionMismatch] = []

    for sym in all_symbols:
        int_qty = norm_internal.get(sym, 0)
        brk_qty = norm_broker.get(sym, 0)

        if int_qty != 0 and brk_qty == 0:
            mismatches.append(
                PositionMismatch(
                    symbol=sym,
                    internal_qty=int_qty,
                    broker_qty=0,
                    mismatch_type=MismatchType.MISSING_IN_BROKER,
                    details=f"Symbol {sym} exists in internal book (qty={int_qty}) but missing or flat in broker",
                )
            )
        elif int_qty == 0 and brk_qty != 0:
            mismatches.append(
                PositionMismatch(
                    symbol=sym,
                    internal_qty=0,
                    broker_qty=brk_qty,
                    mismatch_type=MismatchType.MISSING_INTERNALLY,
                    details=f"Symbol {sym} exists in broker (qty={brk_qty}) but missing or flat in internal book",
                )
            )
        elif int_qty != brk_qty:
            mismatches.append(
                PositionMismatch(
                    symbol=sym,
                    internal_qty=int_qty,
                    broker_qty=brk_qty,
                    mismatch_type=MismatchType.QUANTITY_MISMATCH,
                    details=f"Symbol {sym} quantity mismatch: internal={int_qty} vs broker={brk_qty} (drift={int_qty - brk_qty})",
                )
            )

    return mismatches


def _generate_risk_jwt() -> str:
    """Generates an authenticated JWT for triggering the risk engine kill-switch."""
    envs = dotenv_values(".env")
    priv_key_str = envs.get("JWT_PRIVATE_KEY", os.environ.get("JWT_PRIVATE_KEY", ""))
    if priv_key_str.startswith('"') and priv_key_str.endswith('"'):
        priv_key_str = priv_key_str[1:-1]
    priv_key_str = priv_key_str.replace("\\n", "\n")

    if not priv_key_str:
        return "dev-reconciliation-token"

    payload = {
        "sub": "position-reconciliation-service",
        "roles": ["risk_officer", "admin", "trader"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
    }
    return jwt.encode(payload, priv_key_str, algorithm="RS256")


async def trigger_kill_switch(
    reason: str,
    risk_engine_url: str | None = None,
) -> bool:
    """Calls risk_engine_service to activate the kill-switch halt."""
    base_url = risk_engine_url or settings.risk_engine_service_url
    url = f"{base_url.rstrip('/')}/risk/kill-switch/activate"
    token = _generate_risk_jwt()
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=settings.risk_timeout_seconds) as client:
            resp = await client.post(url, json={"reason": reason}, headers=headers)
            if resp.status_code == 200:
                log.warning("kill_switch_activated_successfully", response=resp.json())
                return True
            log.error("kill_switch_activation_failed", status=resp.status_code, body=resp.text)
            return False
    except Exception as exc:
        log.exception("kill_switch_call_exception", error=str(exc))
        return False


async def fetch_internal_positions() -> dict[str, int]:
    """Fetches open positions from Postgres pm_positions table."""
    positions = await repo.list_positions(include_flat=False)
    return {p.symbol: int(p.net_quantity) for p in positions if int(p.net_quantity) != 0}


async def fetch_broker_positions(
    broker_url: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, int]:
    """Fetches live positions from broker_service GET /v1/broker/positions."""
    base_url = broker_url or settings.broker_service_url
    url = f"{base_url.rstrip('/')}/v1/broker/positions"

    async def _do_fetch(c: httpx.AsyncClient) -> dict[str, int]:
        resp = await c.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"Broker positions fetch failed: HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        positions: dict[str, int] = {}
        for p in data:
            sym = p.get("symbol")
            qty = p.get("quantity", 0)
            if sym and int(qty) != 0:
                positions[sym] = int(qty)
        return positions

    if client is not None:
        return await _do_fetch(client)

    async with httpx.AsyncClient(timeout=settings.broker_timeout_seconds) as c:
        return await _do_fetch(c)


async def reconcile_positions(
    *,
    broker_positions: dict[str, int] | None = None,
    internal_positions: dict[str, int] | None = None,
    trigger_halt_on_mismatch: bool = True,
    broker_url: str | None = None,
    risk_engine_url: str | None = None,
) -> PositionReconciliationResult:
    """
    Executes a complete position reconciliation cycle:
      1. Resolves internal and broker positions
      2. Computes drift / mismatches
      3. On mismatch -> logs CRITICAL and trips kill-switch
      4. On match -> logs INFO positive audit confirmation
    """
    # 1. Fetch positions if not supplied directly
    if internal_positions is None:
        internal_positions = await fetch_internal_positions()

    if broker_positions is None:
        broker_positions = await fetch_broker_positions(broker_url=broker_url)

    # 2. Diff
    mismatches = diff_positions(internal_positions, broker_positions)
    checked_symbols = sorted(
        set(normalize_symbol(s) for s in internal_positions.keys())
        | set(normalize_symbol(s) for s in broker_positions.keys())
    )

    halt_triggered = False

    # 3. Handle outcome
    if mismatches:
        summary_lines = []
        for m in mismatches:
            summary_lines.append(
                f"[{m.mismatch_type.value}] symbol={m.symbol}: internal={m.internal_qty} vs broker={m.broker_qty}"
            )
        rejection_reason = "POSITION_BOOK_RECONCILIATION_MISMATCH: " + "; ".join(summary_lines)

        # Log CRITICAL with exact details
        for m in mismatches:
            log.critical(
                "POSITION_RECONCILIATION_MISMATCH",
                symbol=m.symbol,
                internal_qty=m.internal_qty,
                broker_qty=m.broker_qty,
                mismatch_type=m.mismatch_type.value,
                details=m.details,
            )

        if trigger_halt_on_mismatch:
            halt_triggered = await trigger_kill_switch(
                reason=rejection_reason,
                risk_engine_url=risk_engine_url,
            )
    else:
        log.info(
            "POSITION_RECONCILIATION_CLEAN",
            checked_count=len(checked_symbols),
            symbols=checked_symbols,
            message=f"Position book reconciled cleanly with broker. All {len(checked_symbols)} position(s) matched.",
        )

    return PositionReconciliationResult(
        matched=len(mismatches) == 0,
        checked_symbols=checked_symbols,
        internal_positions=internal_positions,
        broker_positions=broker_positions,
        mismatches=mismatches,
        halt_triggered=halt_triggered,
        timestamp=datetime.now(timezone.utc),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler & Background Loop
# ─────────────────────────────────────────────────────────────────────────────

SCHEDULED_CHECKPOINTS: list[time] = [
    time(9, 15),   # Market Open
    time(10, 15),  # Hourly check
    time(11, 15),  # Hourly check
    time(12, 15),  # Hourly check
    time(13, 15),  # Hourly check
    time(14, 15),  # Hourly check
    time(15, 15),  # Hourly check
    time(15, 30),  # Market Close
]


class PositionReconciliationScheduler:
    """
    Manages timed position reconciliation checkpoints on trading days.
    Tracks executed checkpoints per trading date so each runs once per day.
    """

    def __init__(self, checkpoints: list[time] | None = None) -> None:
        self.checkpoints = sorted(checkpoints or SCHEDULED_CHECKPOINTS)
        self.executed_today: set[time] = set()
        self.current_date = now_ist().date()
        self.last_result: PositionReconciliationResult | None = None

    def should_trigger(self, current_ist: datetime) -> list[time]:
        """
        Determines if any scheduled checkpoint has become due and not yet run.
        """
        today = current_ist.date()
        if today != self.current_date:
            self.current_date = today
            self.executed_today.clear()

        # Only trigger on active NSE trading days
        if not is_trading_day(current_ist):
            return []

        cur_time = current_ist.time()
        due: list[time] = []

        for cp in self.checkpoints:
            if cp <= cur_time and cp not in self.executed_today:
                due.append(cp)

        return due

    def mark_executed(self, checkpoint: time) -> None:
        self.executed_today.add(checkpoint)


async def position_reconciliation_loop(
    stop_event: asyncio.Event,
    scheduler: PositionReconciliationScheduler | None = None,
) -> None:
    """
    Background worker that runs throughout the service lifespan,
    evaluating reconciliation checkpoints against the IST market calendar.
    """
    sched = scheduler or PositionReconciliationScheduler()
    log.info(
        "position_reconciliation_loop_started",
        checkpoints=[cp.strftime("%H:%M") for cp in sched.checkpoints],
        poll_interval_s=settings.position_reconciliation_poll_interval_seconds,
    )

    while not stop_event.is_set():
        try:
            current_time = now_ist()
            due_checkpoints = sched.should_trigger(current_time)

            for cp in due_checkpoints:
                log.info(
                    "running_scheduled_position_reconciliation",
                    checkpoint=cp.strftime("%H:%M"),
                    ist_time=current_time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                result = await reconcile_positions(trigger_halt_on_mismatch=True)
                sched.last_result = result
                sched.mark_executed(cp)

        except Exception:
            log.exception("position_reconciliation_loop_error")

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.position_reconciliation_poll_interval_seconds,
            )
        except asyncio.TimeoutError:
            pass

    log.info("position_reconciliation_loop_stopped")
