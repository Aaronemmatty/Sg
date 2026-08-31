from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import settings


class AnalysisCapability(str, Enum):
    TRADE_REVIEW = "trade_review"
    PORTFOLIO_REVIEW = "portfolio_review"
    RISK_EXPLANATION = "risk_explanation"
    MARKET_SUMMARY = "market_summary"
    PERFORMANCE_EXPLANATION = "performance_explanation"


PerformanceWindow = Literal["1d", "7d", "30d", "90d", "252d", "inception"]


# ─────────────────────────────────────────────────────────────────────────────
# Per-capability request payloads
# ─────────────────────────────────────────────────────────────────────────────

class _BaseAnalysisRequest(BaseModel):
    """user_note is the one place free-text from a human enters the system.
    It is always treated as untrusted DATA in the prompt, never as
    instructions — see services/prompt_manager.py."""

    user_note: str | None = Field(default=None, max_length=settings.max_user_note_chars)
    stream: bool = False

    @field_validator("user_note")
    @classmethod
    def _strip_note(cls, v: str | None) -> str | None:
        return v.strip() if v else v


class TradeReviewRequest(_BaseAnalysisRequest):
    trade_id: uuid.UUID | None = None
    symbol: str | None = None
    lookback_days: int = Field(default=7, gt=0, le=90)


class PortfolioReviewRequest(_BaseAnalysisRequest):
    include_positions: bool = True


class RiskExplanationRequest(_BaseAnalysisRequest):
    symbol: str | None = None


class MarketSummaryRequest(_BaseAnalysisRequest):
    symbols: list[str] = Field(..., min_length=1, max_length=20)


class PerformanceExplanationRequest(_BaseAnalysisRequest):
    window: PerformanceWindow = "30d"


# ─────────────────────────────────────────────────────────────────────────────
# LLM abstraction
# ─────────────────────────────────────────────────────────────────────────────

class LLMMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    system: str
    messages: list[LLMMessage]
    max_tokens: int = Field(default=1024, gt=0)
    temperature: float = Field(default=0.3, ge=0, le=1)
    stream: bool = False


class LLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    text: str
    model: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    stop_reason: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Prompt templates
# ─────────────────────────────────────────────────────────────────────────────

class PromptTemplate(BaseModel):
    id: uuid.UUID
    capability: AnalysisCapability
    version: int
    system_prompt: str
    user_template: str
    is_active: bool
    created_at: datetime
    created_by: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Analysis result
# ─────────────────────────────────────────────────────────────────────────────

class AnalysisResult(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    capability: AnalysisCapability
    generated_at: datetime
    model: str
    text: str
    cached: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_version: int | None = None
    context_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class AuditLogEntry(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_sub: str
    capability: AnalysisCapability
    cache_hit: bool
    status: Literal["success", "error", "rate_limited"]
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
