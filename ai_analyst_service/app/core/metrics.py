from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

ANALYSIS_REQUESTS = Counter(
    "ai_analysis_requests_total", "Total analysis requests", ["capability", "status"]
)
ANALYSIS_DURATION_SECONDS = Histogram(
    "ai_analysis_duration_seconds",
    "End-to-end analysis request duration",
    ["capability"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
)
LLM_CALLS = Counter("ai_llm_calls_total", "Total LLM provider calls", ["provider", "status"])
LLM_CALL_DURATION_SECONDS = Histogram(
    "ai_llm_call_duration_seconds",
    "LLM provider call latency",
    ["provider"],
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60),
)
LLM_TOKENS_USED = Counter(
    "ai_llm_tokens_total", "Total LLM tokens consumed", ["provider", "token_type"]
)
CACHE_HITS = Counter("ai_cache_hits_total", "Cache hits", ["capability"])
CACHE_MISSES = Counter("ai_cache_misses_total", "Cache misses", ["capability"])
RATE_LIMIT_REJECTIONS = Counter(
    "ai_rate_limit_rejections_total", "Requests rejected by the rate limiter", ["scope"]
)
UPSTREAM_CLIENT_ERRORS = Counter(
    "ai_upstream_client_errors_total",
    "Errors calling upstream read-only data services",
    ["service"],
)
ACTIVE_ANALYSIS_REQUESTS = Gauge(
    "ai_active_analysis_requests", "Analysis requests currently in flight"
)
