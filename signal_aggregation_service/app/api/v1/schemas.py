"""API-facing schemas. Thin re-exports/wrappers over domain models."""
from __future__ import annotations

from pydantic import BaseModel

from app.models.domain import (  # noqa: F401 - re-exported for API layer use
    AggregatedSignalResult,
    WeightOverrideRequest,
    WeightOverrideResponse,
)


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadyResponse(BaseModel):
    status: str
    database: bool
    redis: bool


class RecalculateRequest(BaseModel):
    symbol: str
    timeframe: str | None = None


class RecalculateResponse(BaseModel):
    triggered: list[str]


class ContractExampleResponse(BaseModel):
    """Exactly the minimal shape from the brief's example output."""

    symbol: str
    final_signal: str
    confidence: float
    contributors: list[str]
