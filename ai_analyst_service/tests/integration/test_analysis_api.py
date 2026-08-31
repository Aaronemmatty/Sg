from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.llm.base import LLMProviderError
from app.models.domain import AnalysisCapability, AnalysisResult, PromptTemplate
from app.services.rate_limiter import RateLimitExceeded


def _result(capability: AnalysisCapability) -> AnalysisResult:
    return AnalysisResult(
        capability=capability,
        generated_at=datetime.now(timezone.utc),
        model="claude-sonnet-4-6",
        text="This is the analysis explanation.",
        prompt_version=1,
        input_tokens=120,
        output_tokens=80,
    )


@pytest.mark.asyncio
async def test_portfolio_review_returns_analysis_result(api):
    client, mocks = api
    mocks["analysis_service"].prepare.return_value = "prepared-sentinel"
    mocks["analysis_service"].run.return_value = _result(AnalysisCapability.PORTFOLIO_REVIEW)

    resp = await client.post("/api/v1/analysis/portfolio-review", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "This is the analysis explanation."
    assert body["capability"] == "portfolio_review"
    mocks["portfolio_client"].get_snapshot.assert_awaited_once()


@pytest.mark.asyncio
async def test_trade_review_returns_analysis_result(api):
    client, mocks = api
    mocks["analysis_service"].prepare.return_value = "prepared-sentinel"
    mocks["analysis_service"].run.return_value = _result(AnalysisCapability.TRADE_REVIEW)

    resp = await client.post(
        "/api/v1/analysis/trade-review", json={"symbol": "RELIANCE", "lookback_days": 3}
    )

    assert resp.status_code == 200
    assert resp.json()["capability"] == "trade_review"


@pytest.mark.asyncio
async def test_market_summary_requires_at_least_one_symbol(api):
    client, _mocks = api
    resp = await client.post("/api/v1/analysis/market-summary", json={"symbols": []})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_rate_limited_request_returns_429(api):
    client, mocks = api
    mocks["analysis_service"].prepare.side_effect = RateLimitExceeded("user", 10)

    resp = await client.post("/api/v1/analysis/portfolio-review", json={})

    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_llm_provider_error_returns_502(api):
    client, mocks = api
    mocks["analysis_service"].prepare.return_value = "prepared-sentinel"
    mocks["analysis_service"].run.side_effect = LLMProviderError("model unavailable")

    resp = await client.post("/api/v1/analysis/portfolio-review", json={})

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_risk_explanation_endpoint(api):
    client, mocks = api
    mocks["analysis_service"].prepare.return_value = "prepared-sentinel"
    mocks["analysis_service"].run.return_value = _result(AnalysisCapability.RISK_EXPLANATION)

    resp = await client.post("/api/v1/analysis/risk-explanation", json={"symbol": "TCS"})

    assert resp.status_code == 200
    mocks["risk_client"].get_symbol_risk.assert_awaited_once_with("TCS")


@pytest.mark.asyncio
async def test_performance_explanation_endpoint(api):
    client, mocks = api
    mocks["analysis_service"].prepare.return_value = "prepared-sentinel"
    mocks["analysis_service"].run.return_value = _result(AnalysisCapability.PERFORMANCE_EXPLANATION)

    resp = await client.post("/api/v1/analysis/performance-explanation", json={"window": "30d"})

    assert resp.status_code == 200
    mocks["portfolio_client"].get_performance.assert_awaited_once_with("30d")


@pytest.mark.asyncio
async def test_health_endpoint(api):
    client, _mocks = api
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "ai_analyst_service"


@pytest.mark.asyncio
async def test_admin_list_prompts(api):
    client, mocks = api
    template = PromptTemplate(
        id=uuid.uuid4(),
        capability=AnalysisCapability.PORTFOLIO_REVIEW,
        version=1,
        system_prompt="sys",
        user_template="usr",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )
    mocks["repo"].list_templates.return_value = [template]

    resp = await client.get("/api/v1/admin/prompts")

    assert resp.status_code == 200
    assert len(resp.json()) == 1


@pytest.mark.asyncio
async def test_admin_activate_unknown_version_404(api):
    client, mocks = api
    mocks["repo"].activate_template.return_value = None

    resp = await client.post("/api/v1/admin/prompts/portfolio_review/activate/99")

    assert resp.status_code == 404
