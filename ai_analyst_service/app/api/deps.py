from __future__ import annotations

from fastapi import Request

from app.clients.execution_client import ExecutionClient
from app.clients.market_data_client import MarketDataClient
from app.clients.portfolio_client import PortfolioClient
from app.clients.risk_client import RiskClient
from app.db.repository import AnalystRepository
from app.services.analysis_service import AnalysisService
from app.services.prompt_manager import PromptManager


def get_analysis_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


def get_repository(request: Request) -> AnalystRepository:
    return request.app.state.repo


def get_prompt_manager(request: Request) -> PromptManager:
    return request.app.state.prompt_manager


def get_portfolio_client(request: Request) -> PortfolioClient:
    return request.app.state.portfolio_client


def get_risk_client(request: Request) -> RiskClient:
    return request.app.state.risk_client


def get_execution_client(request: Request) -> ExecutionClient:
    return request.app.state.execution_client


def get_market_data_client(request: Request) -> MarketDataClient:
    return request.app.state.market_data_client
