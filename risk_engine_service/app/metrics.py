from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

INTENTS_EVALUATED = Counter(
    "risk_engine_intents_evaluated_total",
    "Total trade intents evaluated by the risk engine",
    ["symbol", "status"],
)

REJECTION_REASONS = Counter(
    "risk_engine_rejections_total",
    "Count of risk rejection reasons fired",
    ["symbol", "reason"],
)

EVALUATION_LATENCY = Histogram(
    "risk_engine_evaluation_seconds",
    "Time taken to evaluate a single trade intent end to end",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

RISK_SCORE_GAUGE = Gauge(
    "risk_engine_last_risk_score",
    "Last computed composite risk score per symbol",
    ["symbol"],
)

KILL_SWITCH_STATE = Gauge(
    "risk_engine_kill_switch_state",
    "Current kill switch state (1=active, 0=normal) by state label",
    ["state"],
)

CIRCUIT_BREAKER_TRIPPED = Gauge(
    "risk_engine_circuit_breaker_tripped",
    "1 if circuit breaker is tripped for symbol, else 0",
    ["symbol"],
)

MARGIN_CHECK_FALLBACKS = Counter(
    "risk_engine_margin_fallback_total",
    "Number of times margin check fell back to cached/mock data",
    ["reason"],
)

VAR_BREACH_TOTAL = Counter(
    "risk_engine_var_breach_total",
    "Number of VaR limit breaches detected",
    ["symbol"],
)
