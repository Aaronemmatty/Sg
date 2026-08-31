from __future__ import annotations

from typing import AsyncIterator

import httpx
import tenacity
from httpx_sse import aconnect_sse

from app.core.config import settings
from app.core.logging import log
from app.core.metrics import LLM_CALL_DURATION_SECONDS, LLM_CALLS, LLM_TOKENS_USED
from app.llm.base import LLMProvider, LLMProviderError
from app.models.domain import LLMRequest, LLMResponse, LLMUsage

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS_CODES
    return False


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        if not settings.anthropic_api_key and settings.env == "production":
            log.error("anthropic_api_key_missing_in_production")
        self._client = client or httpx.AsyncClient(
            base_url=settings.anthropic_base_url,
            timeout=settings.llm_request_timeout_seconds,
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": settings.anthropic_api_version,
                "content-type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _payload(self, request: LLMRequest) -> dict:
        return {
            "model": settings.anthropic_model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not settings.anthropic_api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY is not configured")

        payload = self._payload(request)

        @tenacity.retry(
            stop=tenacity.stop_after_attempt(settings.llm_max_retries),
            wait=tenacity.wait_exponential(multiplier=0.5, max=8),
            retry=tenacity.retry_if_exception(_is_retryable_http_error),
            reraise=True,
        )
        async def _call() -> httpx.Response:
            resp = await self._client.post("/v1/messages", json=payload)
            resp.raise_for_status()
            return resp

        with LLM_CALL_DURATION_SECONDS.labels(provider=self.name).time():
            try:
                resp = await _call()
            except httpx.HTTPStatusError as exc:
                LLM_CALLS.labels(provider=self.name, status="error").inc()
                body = exc.response.text[:500]
                raise LLMProviderError(
                    f"Anthropic API error {exc.response.status_code}: {body}"
                ) from exc
            except httpx.HTTPError as exc:
                LLM_CALLS.labels(provider=self.name, status="error").inc()
                raise LLMProviderError(f"Anthropic API call failed: {exc}") from exc

        data = resp.json()
        text_parts = [
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        ]
        usage = data.get("usage", {})

        LLM_CALLS.labels(provider=self.name, status="success").inc()
        LLM_TOKENS_USED.labels(provider=self.name, token_type="input").inc(usage.get("input_tokens", 0))
        LLM_TOKENS_USED.labels(provider=self.name, token_type="output").inc(usage.get("output_tokens", 0))

        return LLMResponse(
            text="".join(text_parts),
            model=data.get("model", settings.anthropic_model),
            usage=LLMUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            ),
            stop_reason=data.get("stop_reason"),
        )

    async def generate_stream(self, request: LLMRequest) -> AsyncIterator[str]:
        if not settings.anthropic_api_key:
            raise LLMProviderError("ANTHROPIC_API_KEY is not configured")

        payload = self._payload(request)
        payload["stream"] = True

        try:
            async with aconnect_sse(
                self._client, "POST", "/v1/messages", json=payload
            ) as event_source:
                async for sse in event_source.aiter_sse():
                    if sse.event != "content_block_delta":
                        continue
                    try:
                        data = sse.json()
                    except ValueError:
                        continue
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text
            LLM_CALLS.labels(provider=self.name, status="success").inc()
        except httpx.HTTPError as exc:
            LLM_CALLS.labels(provider=self.name, status="error").inc()
            raise LLMProviderError(f"Anthropic streaming call failed: {exc}") from exc
