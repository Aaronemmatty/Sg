"""Security and observability middleware stack."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.logging import get_logger, set_correlation_id

log = get_logger(__name__)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Inject / propagate X-Correlation-ID on every request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        cid = request.headers.get("X-Correlation-ID") or secrets.token_hex(16)
        set_correlation_id(cid)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds hardened HTTP security headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "strict-origin-when-cross-origin",
                "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
                "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
                "Cache-Control": "no-store",
            }
        )
        # Remove fingerprinting headers (MutableHeaders has no .pop())
        for header in ("Server", "X-Powered-By"):
            if header in response.headers:
                del response.headers[header]
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured access log with latency."""

    _SKIP_PATHS = {"/health", "/metrics", "/ready"}

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self._SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_ip=request.client.host if request.client else None,
        )
        return response
