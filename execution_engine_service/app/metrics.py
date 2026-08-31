"""
Custom Prometheus metrics. prometheus-fastapi-instrumentator (wired in main.py)
covers HTTP-layer metrics automatically; these cover the domain-specific
execution workflow that instrumentator can't see.
"""
from prometheus_client import Counter, Histogram

orders_received_total = Counter(
    "execution_orders_received_total", "RiskDecisions received from sg:risk_approved:*", ["status"]
)

orders_placed_total = Counter(
    "execution_orders_placed_total", "Orders submitted to broker_service", ["symbol", "order_type"]
)

orders_filled_total = Counter(
    "execution_orders_filled_total", "Orders that reached FILLED", ["symbol"]
)

orders_terminal_total = Counter(
    "execution_orders_terminal_total", "Orders reaching any terminal state", ["state"]
)

broker_call_failures_total = Counter(
    "execution_broker_call_failures_total", "Failed broker_service calls", ["operation"]
)

order_retry_total = Counter(
    "execution_order_retry_total", "Order placement retries", ["symbol"]
)

held_intents_expired_total = Counter(
    "execution_held_intents_expired_total", "RISK_HOLD intents that aged out unresolved", ["symbol"]
)

reconciliation_mismatches_total = Counter(
    "execution_reconciliation_mismatches_total", "Local/broker state mismatches found during reconciliation", ["symbol"]
)

slippage_bps_histogram = Histogram(
    "execution_slippage_bps",
    "Slippage in basis points per fill (positive = worse than intended)",
    buckets=(-50, -20, -10, -5, -2, 0, 2, 5, 10, 20, 50, 100),
)

broker_call_latency_seconds = Histogram(
    "execution_broker_call_latency_seconds", "broker_service call latency", ["operation"]
)

order_lifecycle_duration_seconds = Histogram(
    "execution_order_lifecycle_duration_seconds",
    "Time from order creation to terminal state",
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
)
