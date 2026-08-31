"""Prometheus metrics — execution orchestrator."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Signal intake ─────────────────────────────────────────────────────────────

SIGNALS_RECEIVED = Counter(
    "eo_signals_received_total",
    "Total aggregated signals received from Redis pub/sub",
    ["symbol"],
)

# ── Eligibility pipeline ──────────────────────────────────────────────────────

ELIGIBILITY_CHECKS = Counter(
    "eo_eligibility_checks_total",
    "Total eligibility checks run",
    ["symbol", "status"],  # status: ELIGIBLE | REJECTED | HOLD
)

REJECTION_REASONS = Counter(
    "eo_rejection_reasons_total",
    "Breakdown of rejection reasons",
    ["symbol", "reason"],
    # reason: low_confidence | excess_exposure | risk_violation |
    #         correlation_violation | liquidity_violation |
    #         daily_loss_limit | position_limit | drawdown_limit
)

# ── Trade intents ─────────────────────────────────────────────────────────────

INTENTS_PUBLISHED = Counter(
    "eo_intents_published_total",
    "Trade intents published to sg:intents channel",
    ["symbol", "action"],
)

INTENTS_PERSISTED = Counter(
    "eo_intents_persisted_total",
    "Trade intents persisted to DB",
    ["symbol", "status"],
)

INTENTS_PERSIST_ERRORS = Counter(
    "eo_intents_persist_errors_total",
    "DB persist failures for trade intents",
    ["symbol"],
)

# ── Allocation ────────────────────────────────────────────────────────────────

ALLOCATION_INR = Histogram(
    "eo_allocation_inr",
    "Recommended capital allocation per intent (INR)",
    ["symbol"],
    buckets=[1_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000],
)

# ── State fetching ────────────────────────────────────────────────────────────

STATE_FETCH_LATENCY = Histogram(
    "eo_state_fetch_seconds",
    "Latency of portfolio/risk state fetches",
    ["source", "state_type"],  # source: redis | http
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

STATE_FETCH_ERRORS = Counter(
    "eo_state_fetch_errors_total",
    "Failures fetching portfolio or risk state",
    ["state_type", "source"],
)

# ── Orchestration latency ─────────────────────────────────────────────────────

ORCHESTRATION_LATENCY = Histogram(
    "eo_orchestration_latency_seconds",
    "End-to-end orchestration latency per signal",
    ["symbol"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# ── Open intents gauge ────────────────────────────────────────────────────────

OPEN_INTENTS = Gauge(
    "eo_open_intents",
    "Currently open ELIGIBLE intents in DB",
)

# ── Consumer health ───────────────────────────────────────────────────────────

CONSUMER_RECONNECTS = Counter(
    "eo_consumer_reconnects_total",
    "Number of Redis pub/sub reconnection attempts",
    ["consumer"],
)

CONSUMER_ERRORS = Counter(
    "eo_consumer_errors_total",
    "Errors in Redis pub/sub message handling",
    ["consumer"],
)
