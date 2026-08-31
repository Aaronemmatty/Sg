"""API-facing schemas. Thin wrappers/aliases over domain models, kept separate so the
wire contract can evolve independently from internal engine types."""
from __future__ import annotations

from app.models.domain import (  # noqa: F401 - re-exported for API layer use
    BacktestRequest,
    BacktestResponse,
    RegimeResult,
    RegimeTransition,
    RegimeType,
)
from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadyResponse(BaseModel):
    status: str
    database: bool
    redis: bool
    classifier_loaded: bool


class RecalculateRequest(BaseModel):
    symbol: str
    timeframe: str | None = None


class RecalculateResponse(BaseModel):
    triggered: list[str]


class TransitionHistoryResponse(BaseModel):
    symbol: str
    timeframe: str
    transitions: list[RegimeTransition]
