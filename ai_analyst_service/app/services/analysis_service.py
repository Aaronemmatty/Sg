from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.core.config import settings
from app.core.logging import log
from app.core.metrics import ANALYSIS_DURATION_SECONDS, ANALYSIS_REQUESTS
from app.db.repository import AnalystRepository
from app.llm.base import LLMProvider, LLMProviderError
from app.models.domain import (
    AnalysisCapability,
    AnalysisResult,
    AuditLogEntry,
    LLMMessage,
    LLMRequest,
)
from app.services.cache_service import AnalysisCache, build_cache_key
from app.services.prompt_manager import PromptManager
from app.services.rate_limiter import RateLimitExceeded, RateLimiter
from app.services.security import render_user_template, sanitize_text, truncate_json_context


@dataclass
class PreparedAnalysis:
    capability: AnalysisCapability
    cache_key: str
    system_prompt: str
    prompt_version: int
    user_message: str
    warnings: list[str]
    user_sub: str
    started_at: float
    cached_result: AnalysisResult | None = None


class AnalysisService:
    """Orchestrates cache lookups, rate limiting, prompt rendering, and LLM
    calls for all five analysis capabilities.

    Two-phase API by design: `prepare()` does everything that's allowed to
    fail with an ordinary HTTP status (cache lookup is free; rate limiting
    must run before any response — streamed or not — has started). Callers
    that want a streaming response call `prepare()` first, check
    `cached_result`/catch `RateLimitExceeded` while they can still return a
    normal status code, and only then open an SSE stream via `stream()`.
    Non-streaming callers can just call `run()`, which does both phases.
    """

    def __init__(
        self,
        repo: AnalystRepository,
        prompt_manager: PromptManager,
        cache: AnalysisCache,
        rate_limiter: RateLimiter,
        llm_provider: LLMProvider,
    ) -> None:
        self._repo = repo
        self._prompts = prompt_manager
        self._cache = cache
        self._rate_limiter = rate_limiter
        self._llm = llm_provider

    async def prepare(
        self,
        capability: AnalysisCapability,
        context: dict,
        warnings: list[str],
        user_note: str | None,
        cache_params: dict[str, Any],
        user_sub: str,
    ) -> PreparedAnalysis:
        started_at = time.monotonic()
        template = await self._prompts.get_active_template(capability)
        cache_key = build_cache_key(capability, cache_params, template.version)

        cached = await self._cache.get(cache_key, capability)
        if cached is not None:
            return PreparedAnalysis(
                capability=capability,
                cache_key=cache_key,
                system_prompt=template.system_prompt,
                prompt_version=template.version,
                user_message="",
                warnings=warnings,
                user_sub=user_sub,
                started_at=started_at,
                cached_result=cached,
            )

        context_json = truncate_json_context({**context, "_data_gaps": warnings})
        rendered = render_user_template(
            template.user_template,
            context_json=context_json,
            user_note=sanitize_text(user_note),
        )

        # Rate limiting only applies on a real cache miss — an LLM call is
        # actually about to happen.
        try:
            await self._rate_limiter.check_and_increment(user_sub)
        except RateLimitExceeded as exc:
            await self._audit(
                user_sub, capability, cache_hit=False, status="rate_limited",
                start=started_at, error=str(exc),
            )
            ANALYSIS_REQUESTS.labels(capability=capability.value, status="rate_limited").inc()
            raise

        return PreparedAnalysis(
            capability=capability,
            cache_key=cache_key,
            system_prompt=template.system_prompt,
            prompt_version=template.version,
            user_message=rendered,
            warnings=warnings,
            user_sub=user_sub,
            started_at=started_at,
        )

    async def run(self, prepared: PreparedAnalysis) -> AnalysisResult:
        if prepared.cached_result is not None:
            await self._audit(
                prepared.user_sub, prepared.capability, cache_hit=True,
                status="success", start=prepared.started_at,
            )
            ANALYSIS_REQUESTS.labels(capability=prepared.capability.value, status="cache_hit").inc()
            return prepared.cached_result

        llm_request = LLMRequest(
            system=prepared.system_prompt,
            messages=[LLMMessage(role="user", content=prepared.user_message)],
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )

        try:
            llm_response = await self._llm.generate(llm_request)
        except LLMProviderError as exc:
            await self._audit(
                prepared.user_sub, prepared.capability, cache_hit=False,
                status="error", start=prepared.started_at, error=str(exc),
            )
            ANALYSIS_REQUESTS.labels(capability=prepared.capability.value, status="error").inc()
            raise

        result = AnalysisResult(
            capability=prepared.capability,
            generated_at=datetime.now(timezone.utc),
            model=llm_response.model,
            text=llm_response.text,
            cached=False,
            input_tokens=llm_response.usage.input_tokens,
            output_tokens=llm_response.usage.output_tokens,
            prompt_version=prepared.prompt_version,
            context_summary={"warnings": prepared.warnings},
            warnings=prepared.warnings,
        )
        await self._cache.set(prepared.cache_key, prepared.capability, result)
        await self._audit(
            prepared.user_sub, prepared.capability, cache_hit=False, status="success",
            start=prepared.started_at, input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        ANALYSIS_REQUESTS.labels(capability=prepared.capability.value, status="success").inc()
        return result

    async def stream(self, prepared: PreparedAnalysis) -> AsyncIterator[str]:
        """Only call this after `prepare()` succeeded with no cached_result —
        rate limiting has already been enforced by that point."""
        if prepared.cached_result is not None:
            await self._audit(
                prepared.user_sub, prepared.capability, cache_hit=True,
                status="success", start=prepared.started_at,
            )
            ANALYSIS_REQUESTS.labels(capability=prepared.capability.value, status="cache_hit").inc()
            yield prepared.cached_result.text
            return

        llm_request = LLMRequest(
            system=prepared.system_prompt,
            messages=[LLMMessage(role="user", content=prepared.user_message)],
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
            stream=True,
        )

        chunks: list[str] = []
        try:
            async for delta in self._llm.generate_stream(llm_request):
                chunks.append(delta)
                yield delta
        except LLMProviderError as exc:
            await self._audit(
                prepared.user_sub, prepared.capability, cache_hit=False,
                status="error", start=prepared.started_at, error=str(exc),
            )
            ANALYSIS_REQUESTS.labels(capability=prepared.capability.value, status="error").inc()
            raise

        full_text = "".join(chunks)
        result = AnalysisResult(
            capability=prepared.capability,
            generated_at=datetime.now(timezone.utc),
            model=settings.anthropic_model,
            text=full_text,
            cached=False,
            prompt_version=prepared.prompt_version,
            context_summary={"warnings": prepared.warnings},
            warnings=prepared.warnings,
        )
        await self._cache.set(prepared.cache_key, prepared.capability, result)
        await self._audit(
            prepared.user_sub, prepared.capability, cache_hit=False,
            status="success", start=prepared.started_at,
        )
        ANALYSIS_REQUESTS.labels(capability=prepared.capability.value, status="success").inc()

    async def _audit(
        self,
        user_sub: str,
        capability: AnalysisCapability,
        *,
        cache_hit: bool,
        status: str,
        start: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        latency_ms = (time.monotonic() - start) * 1000
        ANALYSIS_DURATION_SECONDS.labels(capability=capability.value).observe(latency_ms / 1000)
        entry = AuditLogEntry(
            user_sub=user_sub,
            capability=capability,
            cache_hit=cache_hit,
            status=status,  # type: ignore[arg-type]
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=error,
        )
        try:
            await self._repo.write_audit_entry(entry)
        except Exception as exc:  # noqa: BLE001
            log.warning("audit_log_write_failed", error=str(exc))
