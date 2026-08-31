from __future__ import annotations

from typing import Any

import httpx
import tenacity

from app.core.logging import log
from app.core.metrics import UPSTREAM_CLIENT_ERRORS


class BaseServiceClient:
    """Common HTTP plumbing for all read-only upstream clients.

    Every public method on a subclass should call `_get` and return a plain
    dict with an `"available"` flag rather than raising — a single upstream
    outage should degrade that part of the LLM context, not fail the whole
    analysis request. Callers (context_builder.py) surface the gap to the
    model via the prompt so it says "data unavailable" instead of guessing.
    """

    service_label: str = "unknown"

    def __init__(self, base_url: str, timeout: float, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(2),
        wait=tenacity.wait_exponential(multiplier=0.3, max=2),
        retry=tenacity.retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def _get_raw(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        try:
            resp = await self._get_raw(path, params)
            return {"available": True, "data": resp.json()}
        except Exception as exc:  # noqa: BLE001
            UPSTREAM_CLIENT_ERRORS.labels(service=self.service_label).inc()
            log.warning(
                "upstream_client_call_failed",
                service=self.service_label,
                path=path,
                error=str(exc),
            )
            return {"available": False, "reason": str(exc)}
