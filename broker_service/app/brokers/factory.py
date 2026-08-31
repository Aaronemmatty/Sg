"""
Broker Factory — creates and manages the active broker singleton.

Usage:
    broker = await get_broker()   # returns connected broker
    await broker.place_order(...)
"""
from __future__ import annotations

from typing import Optional

from app.brokers.interface import BrokerInterface
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

_broker: Optional[BrokerInterface] = None


async def create_broker(mode: str | None = None) -> BrokerInterface:
    """
    Factory function — creates the appropriate broker.

    mode: "live" → KiteBroker
          "paper" → PaperBroker
          None → reads from settings.BROKER_MODE
    """
    effective_mode = mode or settings.BROKER_MODE

    if effective_mode == "live":
        from app.brokers.kite.broker import KiteBroker
        broker = KiteBroker()
    elif effective_mode == "paper":
        from app.brokers.paper.broker import PaperBroker
        broker = PaperBroker()
    else:
        raise ValueError(f"Unknown broker mode: {effective_mode}")

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
        log.info("broker_shutdown")
