"""App state — singleton holders for shared objects."""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.consumers.signal_consumer import SignalConsumer
    from app.services.orchestrator_service import OrchestratorService

_consumer: Optional["SignalConsumer"] = None
_orchestrator: Optional["OrchestratorService"] = None


def set_consumer(c: "SignalConsumer") -> None:
    global _consumer
    _consumer = c


def get_consumer() -> Optional["SignalConsumer"]:
    return _consumer


def set_orchestrator_service(svc: "OrchestratorService") -> None:
    global _orchestrator
    _orchestrator = svc


def get_orchestrator_service() -> "OrchestratorService":
    if _orchestrator is None:
        raise RuntimeError("OrchestratorService not initialised")
    return _orchestrator
