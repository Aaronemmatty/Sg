from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any

from app.logging_setup import get_logger
from app.metrics import KILL_SWITCH_STATE
from app.redis_bus import RedisBus
from app.repository import Database

log = get_logger(module="kill_switch")

KILL_SWITCH_KEY = "sg:risk:kill_switch:state"


class KillSwitchState(str, Enum):
    NORMAL = "NORMAL"
    HALTED_MANUAL = "HALTED_MANUAL"
    HALTED_AUTO_DRAWDOWN = "HALTED_AUTO_DRAWDOWN"
    HALTED_AUTO_DAILY_LOSS = "HALTED_AUTO_DAILY_LOSS"
    HALTED_AUTO_CIRCUIT_BREAKER = "HALTED_AUTO_CIRCUIT_BREAKER"
    EMERGENCY_STOP = "EMERGENCY_STOP"

    @property
    def is_automatic(self) -> bool:
        return self in (
            KillSwitchState.HALTED_AUTO_DRAWDOWN,
            KillSwitchState.HALTED_AUTO_DAILY_LOSS,
            KillSwitchState.HALTED_AUTO_CIRCUIT_BREAKER,
            KillSwitchState.EMERGENCY_STOP,
        )

    @property
    def is_halted(self) -> bool:
        return self != KillSwitchState.NORMAL


class KillSwitch:
    """Global trading halt state machine.

    Design (institutional-grade safety): both manual and automatic
    triggers are supported, but automatic breach-triggered halts are a
    hard stop — a plain "deactivate" call from an operator cannot clear
    them. Clearing an automatic halt requires the explicit `reset`
    action, which is role-gated (risk_officer) and is logged as a
    distinct, audited event from a routine manual pause/resume. This
    prevents a single careless API call from silently re-enabling
    trading after a real risk breach.
    """

    def __init__(self, redis_bus: RedisBus, db: Database, reset_role: str) -> None:
        self._redis = redis_bus
        self._db = db
        self._reset_role = reset_role
        self._lock = asyncio.Lock()
        self._state = KillSwitchState.NORMAL
        self._reason: str | None = None

    async def load(self) -> None:
        cached = await self._redis.get_hot_key(KILL_SWITCH_KEY)
        if cached:
            self._state = KillSwitchState(cached.get("state", KillSwitchState.NORMAL.value))
            self._reason = cached.get("reason")
        self._publish_metric()

    def _publish_metric(self) -> None:
        for s in KillSwitchState:
            KILL_SWITCH_STATE.labels(state=s.value).set(1 if s == self._state else 0)

    @property
    def state(self) -> KillSwitchState:
        return self._state

    @property
    def reason(self) -> str | None:
        return self._reason

    async def _persist(self) -> None:
        await self._redis.set_hot_key(KILL_SWITCH_KEY, {"state": self._state.value, "reason": self._reason})
        await self._redis.publish_json(
            "sg:risk:events", {"event": "kill_switch_changed", "state": self._state.value, "reason": self._reason}
        )

    async def activate_manual(self, reason: str, actor: str) -> KillSwitchState:
        async with self._lock:
            previous = self._state
            self._state = KillSwitchState.HALTED_MANUAL
            self._reason = reason
            await self._persist()
            self._publish_metric()
            await self._db.insert_kill_switch_event(
                previous.value, self._state.value, reason, "MANUAL", actor, {}
            )
            log.warning("kill_switch_manual_activate", actor=actor, reason=reason)
            return self._state

    async def trigger_automatic(self, state: KillSwitchState, reason: str, metadata: dict[str, Any]) -> KillSwitchState:
        if not state.is_automatic:
            raise ValueError("trigger_automatic requires an automatic state")
        async with self._lock:
            previous = self._state
            # Automatic triggers escalate; never silently downgrade an
            # existing automatic halt to a different automatic reason
            # without recording it, and never let it un-halt anything.
            if previous != state:
                self._state = state
                self._reason = reason
                await self._persist()
                self._publish_metric()
                await self._db.insert_kill_switch_event(
                    previous.value, self._state.value, reason, "AUTOMATIC", "system", metadata
                )
                log.error("kill_switch_auto_trigger", state=state.value, reason=reason, **metadata)
            return self._state

    async def deactivate_manual(self, actor: str) -> KillSwitchState:
        """Routine resume. Only valid from HALTED_MANUAL. Automatic halts
        require `reset_automatic`."""
        async with self._lock:
            if self._state.is_automatic:
                raise PermissionError(
                    f"Cannot deactivate automatic halt '{self._state.value}' via manual resume; use reset endpoint with required role."
                )
            previous = self._state
            self._state = KillSwitchState.NORMAL
            self._reason = None
            await self._persist()
            self._publish_metric()
            await self._db.insert_kill_switch_event(previous.value, self._state.value, "manual_resume", "MANUAL", actor, {})
            log.info("kill_switch_manual_resume", actor=actor)
            return self._state

    async def reset_automatic(self, actor: str, actor_roles: list[str]) -> KillSwitchState:
        if self._reset_role not in actor_roles:
            raise PermissionError(f"Role '{self._reset_role}' required to reset an automatic halt.")
        async with self._lock:
            previous = self._state
            self._state = KillSwitchState.NORMAL
            self._reason = None
            await self._persist()
            self._publish_metric()
            await self._db.insert_kill_switch_event(
                previous.value, self._state.value, "risk_officer_reset", "MANUAL", actor, {"elevated": True}
            )
            log.warning("kill_switch_reset", actor=actor, previous_state=previous.value)
            return self._state

    async def emergency_stop(self, reason: str, actor: str) -> KillSwitchState:
        """Highest severity halt. Treated as automatic-class (requires
        elevated reset) regardless of whether a human or a system
        triggered it, since by definition it represents an emergency
        condition that must be reviewed before resuming."""
        async with self._lock:
            previous = self._state
            self._state = KillSwitchState.EMERGENCY_STOP
            self._reason = reason
            await self._persist()
            self._publish_metric()
            await self._db.insert_kill_switch_event(
                previous.value, self._state.value, reason, "MANUAL", actor, {"severity": "emergency"}
            )
            log.error("emergency_stop_triggered", actor=actor, reason=reason)
            return self._state
