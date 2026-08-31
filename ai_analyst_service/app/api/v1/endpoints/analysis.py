from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from app.api.deps import (
    get_analysis_service,
    get_execution_client,
    get_market_data_client,
    get_portfolio_client,
    get_risk_client,
)
from app.auth import get_current_user
from app.clients.execution_client import ExecutionClient
from app.clients.market_data_client import MarketDataClient
from app.clients.portfolio_client import PortfolioClient
from app.clients.risk_client import RiskClient
from app.llm.base import LLMProviderError
from app.models.domain import (
    AnalysisCapability,
    AnalysisResult,
    MarketSummaryRequest,
    PerformanceExplanationRequest,
    PortfolioReviewRequest,
    RiskExplanationRequest,
    TradeReviewRequest,
)
from app.services.context_builder import (
    build_market_summary_context,
    build_performance_explanation_context,
    build_portfolio_review_context,
    build_risk_explanation_context,
    build_trade_review_context,
)
from app.services.rate_limiter import RateLimitExceeded

router = APIRouter(prefix="/analysis", tags=["analysis"])


def _user_sub(user: dict[str, Any]) -> str:
    return str(user.get("sub", "unknown"))


async def _sse_body(service, prepared):
    try:
        async for delta in service.stream(prepared):
            yield {"event": "delta", "data": delta}
        yield {"event": "done", "data": "{}"}
    except LLMProviderError as exc:
        yield {"event": "error", "data": str(exc)}


async def _handle_prepare(service, capability, context, warnings, user_note, cache_params, user_sub):
    try:
        return await service.prepare(capability, context, warnings, user_note, cache_params, user_sub)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc


async def _run_or_503(service, prepared) -> AnalysisResult:
    try:
        return await service.run(prepared)
    except LLMProviderError as exc:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "not configured" in str(exc)
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/trade-review")
async def trade_review(
    req: TradeReviewRequest,
    service=Depends(get_analysis_service),
    execution_client: ExecutionClient = Depends(get_execution_client),
    portfolio_client: PortfolioClient = Depends(get_portfolio_client),
    user: dict[str, Any] = Depends(get_current_user),
):
    context, warnings = await build_trade_review_context(req, execution_client, portfolio_client)
    cache_params = req.model_dump(exclude={"stream"}, mode="json")
    prepared = await _handle_prepare(
        service, AnalysisCapability.TRADE_REVIEW, context, warnings, req.user_note, cache_params, _user_sub(user)
    )
    if req.stream:
        return EventSourceResponse(_sse_body(service, prepared))
    return await _run_or_503(service, prepared)


@router.post("/portfolio-review")
async def portfolio_review(
    req: PortfolioReviewRequest,
    service=Depends(get_analysis_service),
    portfolio_client: PortfolioClient = Depends(get_portfolio_client),
    user: dict[str, Any] = Depends(get_current_user),
):
    context, warnings = await build_portfolio_review_context(req, portfolio_client)
    cache_params = req.model_dump(exclude={"stream"}, mode="json")
    prepared = await _handle_prepare(
        service, AnalysisCapability.PORTFOLIO_REVIEW, context, warnings, req.user_note, cache_params, _user_sub(user)
    )
    if req.stream:
        return EventSourceResponse(_sse_body(service, prepared))
    return await _run_or_503(service, prepared)


@router.post("/risk-explanation")
async def risk_explanation(
    req: RiskExplanationRequest,
    service=Depends(get_analysis_service),
    risk_client: RiskClient = Depends(get_risk_client),
    user: dict[str, Any] = Depends(get_current_user),
):
    context, warnings = await build_risk_explanation_context(req, risk_client)
    cache_params = req.model_dump(exclude={"stream"}, mode="json")
    prepared = await _handle_prepare(
        service, AnalysisCapability.RISK_EXPLANATION, context, warnings, req.user_note, cache_params, _user_sub(user)
    )
    if req.stream:
        return EventSourceResponse(_sse_body(service, prepared))
    return await _run_or_503(service, prepared)


@router.post("/market-summary")
async def market_summary(
    req: MarketSummaryRequest,
    service=Depends(get_analysis_service),
    market_data_client: MarketDataClient = Depends(get_market_data_client),
    user: dict[str, Any] = Depends(get_current_user),
):
    context, warnings = await build_market_summary_context(req, market_data_client)
    cache_params = req.model_dump(exclude={"stream"}, mode="json")
    prepared = await _handle_prepare(
        service, AnalysisCapability.MARKET_SUMMARY, context, warnings, req.user_note, cache_params, _user_sub(user)
    )
    if req.stream:
        return EventSourceResponse(_sse_body(service, prepared))
    return await _run_or_503(service, prepared)


@router.post("/performance-explanation")
async def performance_explanation(
    req: PerformanceExplanationRequest,
    service=Depends(get_analysis_service),
    portfolio_client: PortfolioClient = Depends(get_portfolio_client),
    user: dict[str, Any] = Depends(get_current_user),
):
    context, warnings = await build_performance_explanation_context(req, portfolio_client)
    cache_params = req.model_dump(exclude={"stream"}, mode="json")
    prepared = await _handle_prepare(
        service, AnalysisCapability.PERFORMANCE_EXPLANATION, context, warnings, req.user_note, cache_params, _user_sub(user)
    )
    if req.stream:
        return EventSourceResponse(_sse_body(service, prepared))
    return await _run_or_503(service, prepared)
