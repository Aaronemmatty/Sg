"""
WeightStore: DB-backed CRUD for `strategy_weight_overrides`, with a short-TTL in-process
cache so the hot aggregation path doesn't hit Postgres on every recompute. Cache is also
invalidated immediately on write (same-process) and on receipt of `sg:weights:updated`
(cross-process, e.g. when an operator edits weights via a different replica/instance).
"""
from __future__ import annotations

import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.db import StrategyWeightOverride

logger = logging.getLogger(__name__)


class WeightStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[str, dict[str, float]] = {}
        self._cache_ts: dict[str, float] = {}

    def get_overrides(self, regime: str) -> dict[str, float]:
        """Synchronous accessor for the WeightingEngine's hot path — reads the cache only.
        Call `refresh(session, regime)` beforehand (the engine does this each cycle)."""
        return self._cache.get(regime, {})

    def is_stale(self, regime: str) -> bool:
        ts = self._cache_ts.get(regime)
        if ts is None:
            return True
        return (time.monotonic() - ts) > self.settings.WEIGHT_CACHE_TTL_SECONDS

    async def refresh(self, session: AsyncSession, regime: str, force: bool = False) -> None:
        if not force and not self.is_stale(regime):
            return
        stmt = select(StrategyWeightOverride).where(
            StrategyWeightOverride.regime == regime,
            StrategyWeightOverride.is_deleted.is_(False),
        )
        rows = (await session.execute(stmt)).scalars().all()
        self._cache[regime] = {r.strategy: r.weight for r in rows}
        self._cache_ts[regime] = time.monotonic()

    def invalidate(self, regime: str | None = None) -> None:
        if regime is None:
            self._cache.clear()
            self._cache_ts.clear()
        else:
            self._cache.pop(regime, None)
            self._cache_ts.pop(regime, None)

    async def upsert(
        self, session: AsyncSession, regime: str, weights: dict[str, float], updated_by: str | None = None
    ) -> dict[str, float]:
        stmt = select(StrategyWeightOverride).where(
            StrategyWeightOverride.regime == regime,
            StrategyWeightOverride.strategy.in_(list(weights.keys())),
        )
        existing = {r.strategy: r for r in (await session.execute(stmt)).scalars().all()}

        for strategy, weight in weights.items():
            if strategy in existing:
                existing[strategy].weight = weight
                existing[strategy].updated_by = updated_by
            else:
                session.add(
                    StrategyWeightOverride(
                        tenant_id=self.settings.DEFAULT_TENANT_ID,
                        regime=regime,
                        strategy=strategy,
                        weight=weight,
                        updated_by=updated_by,
                    )
                )
        await session.flush()
        self.invalidate(regime)
        await self.refresh(session, regime, force=True)
        return self.get_overrides(regime)

    async def get_all_for_regime(self, session: AsyncSession, regime: str) -> dict[str, float]:
        await self.refresh(session, regime, force=True)
        return self.get_overrides(regime)
