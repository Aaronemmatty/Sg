from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.models.domain import AnalysisCapability, PromptTemplate
from app.services.prompt_manager import PromptManager, PromptTemplateNotFoundError


def _template(capability: AnalysisCapability, version: int = 1) -> PromptTemplate:
    return PromptTemplate(
        id=uuid.uuid4(),
        capability=capability,
        version=version,
        system_prompt="You are a helpful analyst.",
        user_template="<data>{context_json}</data><user_note>{user_note}</user_note>",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_get_active_template_returns_repo_result():
    repo = AsyncMock()
    repo.get_active_template.return_value = _template(AnalysisCapability.MARKET_SUMMARY)
    manager = PromptManager(repo)

    result = await manager.get_active_template(AnalysisCapability.MARKET_SUMMARY)
    assert result.capability == AnalysisCapability.MARKET_SUMMARY
    repo.get_active_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_active_template_uses_cache_on_second_call():
    repo = AsyncMock()
    repo.get_active_template.return_value = _template(AnalysisCapability.MARKET_SUMMARY)
    manager = PromptManager(repo)

    await manager.get_active_template(AnalysisCapability.MARKET_SUMMARY)
    await manager.get_active_template(AnalysisCapability.MARKET_SUMMARY)

    # Cached on the second call — repo should only be hit once.
    assert repo.get_active_template.await_count == 1


@pytest.mark.asyncio
async def test_invalidate_forces_repo_refetch():
    repo = AsyncMock()
    repo.get_active_template.return_value = _template(AnalysisCapability.MARKET_SUMMARY)
    manager = PromptManager(repo)

    await manager.get_active_template(AnalysisCapability.MARKET_SUMMARY)
    manager.invalidate(AnalysisCapability.MARKET_SUMMARY)
    await manager.get_active_template(AnalysisCapability.MARKET_SUMMARY)

    assert repo.get_active_template.await_count == 2


@pytest.mark.asyncio
async def test_raises_when_no_active_template_configured():
    repo = AsyncMock()
    repo.get_active_template.return_value = None
    manager = PromptManager(repo)

    with pytest.raises(PromptTemplateNotFoundError):
        await manager.get_active_template(AnalysisCapability.RISK_EXPLANATION)
