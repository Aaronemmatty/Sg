# Open Items — Metric Names to Confirm

Same spirit as the platform's existing "isolate the assumption to one file
and say so" rule for REST contracts (used for `data_loader.py`,
`risk_client.py`, etc. in 8010/8011/8012) — applied here to Prometheus metric
names. Confirmed-vs-assumed status, one row per metric, grouped by the
service that would need to emit it.

**Confirmed (already true platform-wide):** `up`, `http_requests_total{job,handler,status}`,
`http_request_duration_seconds_bucket{job,handler,le}` — guaranteed by the
established `prometheus-fastapi-instrumentator` convention used by all 12
services.

## risk_engine_service (8007)
| Metric | Used in |
|---|---|
| `risk_kill_switch_active` | `RiskKillSwitchActive` alert, trading-pipeline + risk-engine dashboards |
| `risk_intents_rejected_total`, `risk_intents_approved_total` | `RiskRejectionRateSpike` alert, both dashboards |
| `risk_intents_rejected_total{reason}` label | risk-engine dashboard "Rejection Reasons" panel |
| `risk_portfolio_var_inr` | risk-engine dashboard |
| `risk_current_drawdown_pct` | risk-engine dashboard |
| `risk_exposure_inr{symbol}` | risk-engine dashboard |
| `risk_margin_utilisation_pct` | risk-engine dashboard |
| `risk_volatility_score{symbol}` | risk-engine dashboard |

## broker_service (8003)
| Metric | Used in |
|---|---|
| `broker_circuit_breaker_state` | `BrokerCircuitBreakerOpen` alert, trading-pipeline dashboard |

## execution_engine_service (8008)
| Metric | Used in |
|---|---|
| `execution_events_total{event_type}` | `OrderFailureRateSpike` alert, trading-pipeline dashboard. Should map 1:1 to the frozen `ExecutionEvent.event_type` enum already documented in the handover — if 8008 emits a counter at all, this is the most likely shape. |
| `execution_slippage_bps_bucket` (histogram) | trading-pipeline dashboard slippage panel. From `ExecutionEvent.slippage_bps`. |

## execution_orchestrator_service (8006)
| Metric | Used in |
|---|---|
| `orchestrator_signals_approved_total` | trading-pipeline dashboard |

## strategy_service / regime_detection_service (8004/8005)
| Metric | Used in |
|---|---|
| `strategy_signals_generated_total` | trading-pipeline dashboard |

## portfolio_management_service (8009)
| Metric | Used in |
|---|---|
| `pm_portfolio_mtm_value_inr` | trading-pipeline dashboard. **Cross-check against the authoritative source first** — `GET /api/v1/portfolio/snapshot` already returns this; a Prometheus gauge would just be a convenience mirror, not a new source of truth. |
| `pm_portfolio_unrealized_pnl_inr`, `pm_portfolio_realized_pnl_inr` | trading-pipeline dashboard P&L panel. Same caveat — `/performance/{window}` is authoritative. |
| `pm_last_event_processed_timestamp_seconds` | `PortfolioEventLagHigh` alert |

## ml_platform_service (8011)
| Metric | Used in |
|---|---|
| `ml_drift_psi{symbol, model_type, feature}` | `MLModelDriftBreach` alert, ml-platform dashboard. Most likely to already exist in some form — drift computation is a confirmed, built feature (`monitoring/drift_monitor.py`); only the exact exported metric name is unconfirmed. |
| `ml_champion_rolling_accuracy{symbol, model_type}` | `MLChampionAccuracyDegraded` alert, ml-platform dashboard |
| `ml_training_jobs_active`, `ml_training_jobs_total{status}` | ml-platform dashboard |
| `ml_model_promotions_total` | ml-platform dashboard |
| `ml_model_fallback_active{model_type}` | ml-platform dashboard. Ties to the documented "fallback is flagged in metadata, no silent degradation" behavior — check whether that metadata is already mirrored into a gauge anywhere. |
| `ml_signals_published_total` | ml-platform dashboard. Ties to the frozen ML signal contract (`confidence >= 0.55` to publish). |

## ai_analyst_service (8012)
| Metric | Used in |
|---|---|
| `ai_analyst_redis_fail_open_total` | `AIAnalystRateLimiterFailOpen` alert. Ties to documented "fails open on Redis outage" behavior for both cache and rate limiter. |
| `ai_analyst_llm_requests_total{status}` | `AIAnalystLLMErrorRateHigh` alert |

## backtesting_engine_service (8010)
| Metric | Used in |
|---|---|
| `backtest_job_age_seconds{state, run_id}` | `BacktestJobStuckRunning` alert. Ties to the documented known limitation ("a run stuck in RUNNING after a crash is NOT auto-reconciled"). If no such gauge exists, an alternative is a `postgres_exporter` custom query against `bt_runs` directly instead of a gauge in 8010 itself. |

## All services (cross-cutting)
| Metric | Used in |
|---|---|
| `db_pool_in_use_connections`, `db_pool_max_size` | `DBConnectionPoolNearExhaustion` alert, both infra dashboards. Platform convention is `asyncpg.create_pool(min_size=5, max_size=20)` — exposing pool stats as a gauge is new instrumentation, not assumed to exist anywhere yet. |

## How to confirm, fast

```bash
# From inside any service container, or against its /metrics endpoint directly:
curl -s http://localhost:<port>/metrics | grep -E '^(risk_|execution_|orchestrator_|strategy_|pm_|ml_|ai_analyst_|backtest_|broker_|db_pool_)' 
```

Anywhere the grep comes back empty, either add the metric to that service
(quick — a `Counter`/`Gauge` plus one `.inc()`/`.set()` call at the relevant
point) or rename the assumed metric in this PR's alert rules / dashboard JSON
to whatever already exists. Either way, update this table once confirmed.
