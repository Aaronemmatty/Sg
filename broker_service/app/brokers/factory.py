"""
Broker Factory — creates and manages the active broker singleton.

Usage:
    broker = await get_broker()   # returns connected broker
    await broker.place_order(...)
"""
from __future__ import annotations

from typing import Optional

from app.brokers.interface import BrokerInterface, LiveTradingGuardError
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_broker: Optional[BrokerInterface] = None


def verify_live_trading_guard(settings_obj=None) -> None:
    """
    Mandatory hard safety check for live broker initialization.

    Requires BOTH:
      1. BROKER_MODE == "live"
      2. ENABLE_REAL_MONEY_TRADING == "CONFIRMED_REAL_CAPITAL_RISK"
    """
    settings = settings_obj or get_settings()
    confirmation = (getattr(settings, "ENABLE_REAL_MONEY_TRADING", "") or "").strip()
    required_token = getattr(settings, "LIVE_CONFIRMATION_TOKEN", "CONFIRMED_REAL_CAPITAL_RISK")

    if confirmation != required_token:
        error_msg = (
            f"LIVE REAL-MONEY TRADING REFUSED: BROKER_MODE is set to 'live', but "
            f"ENABLE_REAL_MONEY_TRADING does not match the mandatory safety confirmation "
            f"token '{required_token}'. Set ENABLE_REAL_MONEY_TRADING={required_token} "
            f"in deployment configuration to authorize live market execution."
        )
        log.critical("live_trading_guard_blocked", reason=error_msg)
        raise LiveTradingGuardError(error_msg)


async def create_broker(mode: str | None = None) -> BrokerInterface:
    """
    Factory function — creates the appropriate broker.

    mode: "live" → KiteBroker (guarded by ENABLE_REAL_MONEY_TRADING)
          "paper" → PaperBroker (safe default)
          None → reads from settings.BROKER_MODE
    """
    settings = get_settings()
    effective_mode = mode or settings.BROKER_MODE

    if effective_mode == "live":
        # Hard fail-closed safety guard
        verify_live_trading_guard(settings)
        from app.brokers.kite.broker import KiteBroker
        broker = KiteBroker()
    elif effective_mode == "paper":
        from app.brokers.paper.broker import PaperBroker
        broker = PaperBroker()
    else:
        raise ValueError(f"Unknown broker mode: '{effective_mode}'. Supported modes: 'paper', 'live'")

    await broker.connect()
    log.info("broker_created", broker=broker.broker_name, mode=effective_mode)
    return broker


async def get_broker() -> BrokerInterface:
    """Return the connected broker singleton. Raises if not initialised."""
    if _broker is None:
        raise RuntimeError("Broker not initialised. Call init_broker() at startup.")
    return _broker


async def init_broker(mode: str | None = None) -> BrokerInterface:
    """Called at application startup to create and connect the broker."""
    global _broker
    _broker = await create_broker(mode)
    return _broker


async def shutdown_broker() -> None:
    """Called at application shutdown."""
    global _broker
    if _broker:
        await _broker.disconnect()
        _broker = None
