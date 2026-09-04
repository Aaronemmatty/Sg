from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"


class StrategySourceType(str, Enum):
    REGISTRY = "registry"   # load from strategy_service by name/id
    INLINE = "inline"        # self-contained JSON rule config


class BacktestStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BacktestMode(str, Enum):
    SINGLE = "single"
    WALK_FORWARD = "walk_forward"
    MONTE_CARLO = "monte_carlo"


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


# ─────────────────────────────────────────────────────────────────────────────
# Market data
# ─────────────────────────────────────────────────────────────────────────────

class OHLCVBar(BaseModel):
    symbol: str
    timeframe: Timeframe
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Strategy reference
# ─────────────────────────────────────────────────────────────────────────────

class StrategyRef(BaseModel):
    """How a backtest sources its trading logic.

    REGISTRY: defers to strategy_service (8004) for the StrategyBase
              implementation identified by `name`, optionally parameterised
              with `params` (overrides on top of the registered defaults).
    INLINE:   fully self-contained — a JSON rule set evaluated locally by
              the engine's built-in rule interpreter, no 8004 dependency.
    """

    source: StrategySourceType
    name: str | None = Field(default=None, description="Required when source=registry")
    params: dict[str, Any] = Field(default_factory=dict)
    inline_rules: dict[str, Any] | None = Field(
        default=None, description="Required when source=inline; rule-based config"
    )

    @model_validator(mode="after")
    def _validate_source_fields(self) -> "StrategyRef":
        if self.source == StrategySourceType.REGISTRY and not self.name:
            raise ValueError("'name' is required when source=registry")
        if self.source == StrategySourceType.INLINE and not self.inline_rules:
            raise ValueError("'inline_rules' is required when source=inline")
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Cost model
# ─────────────────────────────────────────────────────────────────────────────

class TransactionCostConfig(BaseModel):
    commission_bps: float = Field(default=3.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    fixed_cost_inr: float = Field(default=0.0, ge=0)
    slippage_model: Literal["fixed_bps", "volume_scaled", "spread_proxy"] = "fixed_bps"


# ─────────────────────────────────────────────────────────────────────────────
# Backtest configuration / request
# ─────────────────────────────────────────────────────────────────────────────

class WalkForwardConfig(BaseModel):
    train_window_days: int = Field(default=180, gt=0)
    test_window_days: int = Field(default=30, gt=0)
    step_days: int = Field(default=30, gt=0)
    anchored: bool = Field(
        default=False, description="If true, train window start is fixed (expanding window)"
    )


class MonteCarloConfig(BaseModel):
    iterations: int = Field(default=2000, gt=0, le=50000)
    method: Literal["trade_reshuffle", "return_bootstrap", "block_bootstrap"] = (
        "trade_reshuffle"
    )
    block_size: int = Field(default=5, gt=0, description="Used when method=block_bootstrap")
    confidence_levels: list[float] = Field(default_factory=lambda: [0.05, 0.25, 0.5, 0.75, 0.95])
    random_seed: int | None = None


class BacktestConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    symbols: list[str] = Field(..., min_length=1)
    primary_timeframe: Timeframe = Timeframe.D1
    additional_timeframes: list[Timeframe] = Field(default_factory=list)
    start_date: date
    end_date: date
    initial_capital_inr: float | None = Field(default=None, gt=0)
    capital_source: str | None = Field(
        default=None,
        description="Source of starting capital: live-fetched | static-fallback | user-override",
    )
    strategy: StrategyRef
    costs: TransactionCostConfig = Field(default_factory=TransactionCostConfig)
    benchmark_symbol: str | None = "NIFTY50"
    max_position_pct: float = Field(
        default=0.25, gt=0, le=1.0, description="Max fraction of equity per position"
    )
    allow_short: bool = False

    @field_validator("end_date")
    @classmethod
    def _end_after_start(cls, v: date, info: Any) -> date:
        start = info.data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


class BacktestRunRequest(BaseModel):
    mode: BacktestMode = BacktestMode.SINGLE
    config: BacktestConfig
    walk_forward: WalkForwardConfig | None = None
    monte_carlo: MonteCarloConfig | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Results — trades, equity curve
# ─────────────────────────────────────────────────────────────────────────────

class SimulatedTrade(BaseModel):
    trade_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    symbol: str
    action: OrderAction
    entry_ts: datetime
    entry_price_inr: float
    exit_ts: datetime | None = None
    exit_price_inr: float | None = None
    quantity: float
    commission_inr: float = 0.0
    slippage_inr: float = 0.0
    realized_pnl_inr: float | None = None
    realized_pnl_pct: float | None = None
    holding_period_bars: int | None = None
    exit_reason: str | None = None


class EquityPoint(BaseModel):
    ts: datetime
    equity_inr: float
    cash_inr: float
    drawdown_pct: float
    benchmark_equity_inr: float | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Performance metrics
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceMetrics(BaseModel):
    total_return_pct: float
    cagr_pct: float | None = None
    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    max_drawdown_pct: float
    max_drawdown_duration_days: int | None = None
    volatility_annualized_pct: float | None = None
    win_rate_pct: float | None = None
    profit_factor: float | None = None
    avg_win_inr: float | None = None
    avg_loss_inr: float | None = None
    expectancy_inr: float | None = None
    num_trades: int = 0
    alpha_pct: float | None = None
    beta: float | None = None
    information_ratio: float | None = None
    final_equity_inr: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward
# ─────────────────────────────────────────────────────────────────────────────

class WalkForwardWindowResult(BaseModel):
    window_index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    in_sample_metrics: PerformanceMetrics
    out_sample_metrics: PerformanceMetrics


class WalkForwardResult(BaseModel):
    windows: list[WalkForwardWindowResult]
    aggregate_out_sample_metrics: PerformanceMetrics
    consistency_score_pct: float = Field(
        description="Pct of OOS windows with positive return"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Monte Carlo
# ─────────────────────────────────────────────────────────────────────────────

class MonteCarloPercentile(BaseModel):
    confidence_level: float
    final_equity_inr: float
    total_return_pct: float
    max_drawdown_pct: float


class MonteCarloResult(BaseModel):
    iterations: int
    method: str
    percentiles: list[MonteCarloPercentile]
    probability_of_loss_pct: float
    probability_of_ruin_pct: float = Field(
        description="Probability equity ever fell below 50% of initial capital"
    )
    original_metrics: PerformanceMetrics
    median_metrics: PerformanceMetrics


# ─────────────────────────────────────────────────────────────────────────────
# Backtest run (job) — persisted aggregate
# ─────────────────────────────────────────────────────────────────────────────

class BacktestRun(BaseModel):
    id: uuid.UUID
    mode: BacktestMode
    status: BacktestStatus
    config: BacktestConfig
    walk_forward_config: WalkForwardConfig | None = None
    monte_carlo_config: MonteCarloConfig | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    progress_pct: float = 0.0


class BacktestResultBundle(BaseModel):
    run: BacktestRun
    performance: PerformanceMetrics | None = None
    equity_curve: list[EquityPoint] = Field(default_factory=list)
    trades: list[SimulatedTrade] = Field(default_factory=list)
    walk_forward: WalkForwardResult | None = None
    monte_carlo: MonteCarloResult | None = None
