"""Structured logging."""
from __future__ import annotations
import logging, sys
from contextvars import ContextVar
import structlog
from app.core.config import get_settings
settings = get_settings()
_cid: ContextVar[str] = ContextVar("cid", default="")
def set_correlation_id(c): _cid.set(c)
def get_correlation_id(): return _cid.get()
def _ctx(logger, method, event_dict):
    event_dict["correlation_id"] = _cid.get() or None
    return event_dict
def configure_logging():
    shared = [structlog.contextvars.merge_contextvars, structlog.stdlib.add_logger_name,
              structlog.stdlib.add_log_level, structlog.processors.TimeStamper(fmt="iso"),
              _ctx, structlog.processors.StackInfoRenderer()]
    renderer = structlog.dev.ConsoleRenderer(colors=True) if settings.APP_ENV == "development" else structlog.processors.JSONRenderer()
    structlog.configure(processors=shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
                        logger_factory=structlog.stdlib.LoggerFactory(),
                        wrapper_class=structlog.stdlib.BoundLogger, cache_logger_on_first_use=True)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(structlog.stdlib.ProcessorFormatter(processor=renderer, foreign_pre_chain=shared))
    root = logging.getLogger(); root.addHandler(h); root.setLevel(settings.LOG_LEVEL.upper())
def get_logger(name=__name__): return structlog.get_logger(name)
