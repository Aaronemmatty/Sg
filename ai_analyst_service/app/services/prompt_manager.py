from __future__ import annotations

import time

from app.db.repository import AnalystRepository
from app.models.domain import AnalysisCapability, PromptTemplate

_TEMPLATE_CACHE_TTL_SECONDS = 60


class PromptManager:
    """Wraps AnalystRepository's prompt template lookups with a short-lived
    in-process cache. Templates change rarely (admin action via
    /admin/prompts) so a 60s cache avoids a DB round-trip on every single
    analysis request without meaningfully delaying a template rollout."""

    def __init__(self, repo: AnalystRepository) -> None:
        self._repo = repo
        self._cache: dict[AnalysisCapability, tuple[float, PromptTemplate]] = {}

    async def get_active_template(self, capability: AnalysisCapability) -> PromptTemplate:
        cached = self._cache.get(capability)
        if cached and (time.monotonic() - cached[0]) < _TEMPLATE_CACHE_TTL_SECONDS:
            return cached[1]

        template = await self._repo.get_active_template(capability)
        if template is None:
            raise PromptTemplateNotFoundError(
                f"No active prompt template configured for capability '{capability.value}'. "
                f"Seed one via migrations or POST /api/v1/admin/prompts."
            )
        self._cache[capability] = (time.monotonic(), template)
        return template

    def invalidate(self, capability: AnalysisCapability | None = None) -> None:
        if capability is None:
            self._cache.clear()
        else:
            self._cache.pop(capability, None)


class PromptTemplateNotFoundError(Exception):
    pass
