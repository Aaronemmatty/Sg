"""Structured logging."""
from __future__ import annotations
import logging, sys
from contextvars import ContextVar
import structlog
from app.core.config import get_settings
from sg_security.redaction import redact_sensitive_fields

settings = get_settings()
_cid: ContextVar[str] = ContextVar("correlation_id", default="")

def set_correlation_id(cid: str) -> None: _cid.set(cid)
def get_correlation_id() -> str: return _cid.get()

def _add_ctx(logger, method, event_dict):
    event_dict["correlation_id"] = _cid.get() or None
    return event_dict

def configure_logging() -> None:
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_ctx,
        redact_sensitive_fields,
        structlog.processors.StackInfoRenderer(),
    ]
    renderer = structlog.dev.ConsoleRenderer(colors=True) if settings.APP_ENV == "development" else structlog.processors.JSONRenderer()
    structlog.configure(
        processors=shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(processor=renderer, foreign_pre_chain=shared)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())

def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
