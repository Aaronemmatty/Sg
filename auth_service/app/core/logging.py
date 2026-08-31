"""Structured logging via structlog — JSON in prod, pretty in dev."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

from app.core.config import get_settings

settings = get_settings()

# Context vars propagated through async tasks
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")


def set_correlation_id(cid: str) -> None:
    _correlation_id.set(cid)


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_tenant_id(tid: str) -> None:
    _tenant_id.set(tid)


def set_user_id(uid: str) -> None:
    _user_id.set(uid)


def _add_context(logger: Any, method: str, event_dict: dict) -> dict:
    event_dict["correlation_id"] = _correlation_id.get() or None
    event_dict["tenant_id"] = _tenant_id.get() or None
    event_dict["user_id"] = _user_id.get() or None
    return event_dict


def configure_logging() -> None:
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_context,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.APP_ENV == "development":
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())

    # Quiet noisy libs
    for lib in ("uvicorn.error", "sqlalchemy.engine"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
