from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

BACKTESTS_STARTED = Counter(
    "bt_backtests_started_total", "Total backtests started", ["mode"]
)
BACKTESTS_COMPLETED = Counter(
    "bt_backtests_completed_total", "Total backtests completed", ["mode", "status"]
)
BACKTEST_DURATION_SECONDS = Histogram(
    "bt_backtest_duration_seconds",
    "Wall-clock duration of a backtest run",
    ["mode"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800),
)
BACKTEST_BARS_PROCESSED = Counter(
    "bt_bars_processed_total", "Total OHLCV bars processed across all backtests"
)
ACTIVE_BACKTESTS = Gauge(
    "bt_active_backtests", "Number of backtests currently executing"
)
MONTE_CARLO_ITERATIONS = Counter(
    "bt_monte_carlo_iterations_total", "Total Monte Carlo simulation iterations run"
)
WALK_FORWARD_WINDOWS = Counter(
    "bt_walk_forward_windows_total", "Total walk-forward windows evaluated"
)
DATA_LOADER_FALLBACKS = Counter(
    "bt_data_loader_fallback_total",
    "Times the data loader fell back to DB after REST failure",
)
