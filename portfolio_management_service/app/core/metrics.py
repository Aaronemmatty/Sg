"""
Custom Prometheus metrics for portfolio_management_service (8009).

HTTP-layer metrics are covered by prometheus-fastapi-instrumentator (wired in
main.py). These cover the domain-specific portfolio workflows.
"""
from prometheus_client import Counter, Gauge, Histogram

# ── Fill consumption ─────────────────────────────────────────────────────────

fills_consumed_total = Counter(
    "portfolio_fills_consumed_total",
    "ExecutionEvents consumed from sg:executions:*",
    ["event_type", "symbol"],
)

fill_processing_errors_total = Counter(
    "portfolio_fill_processing_errors_total",
    "Errors processing fill events",
    ["symbol"],
)

# ── Position updates ─────────────────────────────────────────────────────────

position_updates_total = Counter(
    "portfolio_position_updates_total",
    "Position records created or updated",
    ["action", "symbol"],
)

lots_opened_total = Counter(
    "portfolio_lots_opened_total",
    "FIFO lots opened (buy fills)",
    ["symbol"],
)

lots_closed_total = Counter(
    "portfolio_lots_closed_total",
    "FIFO lots fully or partially closed (sell fills)",
    ["symbol"],
)

realized_pnl_inr = Counter(
    "portfolio_realized_pnl_inr_total",
    "Cumulative realized P&L in INR (positive = profit)",
    ["symbol"],
)

# ── Mark-to-market ───────────────────────────────────────────────────────────

mtm_refresh_total = Counter(
    "portfolio_mtm_refresh_total",
    "MTM price refresh cycles completed",
)

mtm_refresh_failures_total = Counter(
    "portfolio_mtm_refresh_failures_total",
    "MTM price fetch failures (symbol unavailable)",
    ["symbol"],
)

portfolio_unrealized_pnl_inr = Gauge(
    "portfolio_unrealized_pnl_inr",
    "Current total unrealized P&L in INR",
)

portfolio_total_value_inr = Gauge(
    "portfolio_total_value_inr",
    "Current total portfolio value (cash + equity) in INR",
)

portfolio_open_positions = Gauge(
    "portfolio_open_positions",
    "Number of symbols with non-zero net position",
)

# ── Snapshot persistence ─────────────────────────────────────────────────────

snapshots_written_total = Counter(
    "portfolio_snapshots_written_total",
    "Portfolio snapshots persisted to sg_db",
)

# ── Performance metrics ──────────────────────────────────────────────────────

sharpe_ratio_gauge = Gauge(
    "portfolio_sharpe_ratio",
    "Rolling annualized Sharpe ratio (30-day window)",
)

max_drawdown_gauge = Gauge(
    "portfolio_max_drawdown_pct",
    "Maximum drawdown from peak (percentage, 0–100)",
)

# ── Latency ──────────────────────────────────────────────────────────────────

fill_processing_latency_seconds = Histogram(
    "portfolio_fill_processing_latency_seconds",
    "Latency to fully process one fill event (DB write + MTM update)",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

snapshot_write_latency_seconds = Histogram(
    "portfolio_snapshot_write_latency_seconds",
    "Time to compute and persist a portfolio snapshot",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
