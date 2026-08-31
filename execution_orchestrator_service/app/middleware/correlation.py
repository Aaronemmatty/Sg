"""Correlation ID middleware — injects per-request ID into structured logs."""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import set_correlation_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Correlation-ID"

    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get(self.HEADER) or str(uuid.uuid4())
        set_correlation_id(cid)
        response = await call_next(request)
        response.headers[self.HEADER] = cid
        return response
