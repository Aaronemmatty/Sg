# Alert Runbook

Every alert below fires to Telegram via Alertmanager (`severity=critical` →
fast group/repeat interval; `severity=warning` → slower). This maps each alert
to a first response. None of this replaces judgment — it's a starting point
for 2am-you.

## Critical

### `ServiceDown`
1. `docker compose ps <service>` — crashed, or just slow to respond to `/health`?
2. Check the service's own logs in Grafana (`infra/service-detail.json`,
   filtered to that service) for a startup/crash stack trace.
3. If it's on the live trading path (8004–8009), check whether the kill
   switch should be engaged manually while it's down — a gap in risk_engine
   or execution_engine means orders can flow unchecked or fills can go
   untracked.
4. Restart: `docker compose restart <service>`. If it loops, check DB/Redis
   connectivity first — most of these services fail closed on startup if
   their dependencies aren't reachable (established platform convention).

### `HighHttp5xxRate`
1. Pull up `infra/service-detail.json` for the affected service → "Requests
   by route + status" panel to find which endpoint is failing.
2. Check error-level logs for the actual exception.
3. If it's an upstream dependency failure (8009/8002/8007/8008 client calls),
   check whether the *upstream* service is healthy first — a downstream 5xx
   spike is often a symptom, not the root cause (see also the
   `ServiceDown`→`HighHttp5xxRate` inhibition rule, which should suppress this
   automatically if the upstream is fully down).

### `RiskKillSwitchActive`
1. This is intentional and expected behavior under bad conditions — it means
   the platform already protected itself. Don't rush to flip it back.
2. Check `sg:risk:events` / the risk dashboard for *why* it triggered (VaR
   breach, drawdown limit, correlation spike, manual trigger).
3. Resolve the underlying condition first, then clear the switch via
   risk_engine's admin path (not currently documented in any handover —
   confirm the actual reset mechanism in 8007's source before assuming one
   exists via REST).

### `OrderFailureRateSpike` / `BrokerCircuitBreakerOpen`
1. Check broker_service (8003) connectivity to Zerodha Kite directly —
   API outage, rate limit, or auth/session expiry are the most common causes.
2. If Kite itself is down, this is expected and the circuit breaker is doing
   its job — confirm paper-trading fallback isn't silently masking it if
   that's not intended.
3. Once broker connectivity is restored, confirm the circuit breaker actually
   closes again (half-open retry behavior) rather than manually forcing it.

### `PostgresDown` / `RedisDown`
1. Treat as platform-wide — every service degrades or fails closed.
2. Check disk space on the Postgres volume first — most outages here are
   disk-full, not a crash.
3. For Redis: the entire live pipeline (`sg:*` channels) stalls. No new
   signals/intents/fills will be processed until it's back — this is *not*
   silently catching up by itself unless services have their own backlog
   replay (most don't, per the "no crash-recovery reconciliation" pattern
   documented for 8010's job state and similar elsewhere).

## Warning

### `HighHttpLatencyP99`
Check for a noisy neighbor (another container hogging CPU — see the
infra-overview CPU panel) before assuming application-level regression.

### `DBConnectionPoolNearExhaustion`
Likely a connection leak (missing `async with pool.acquire()` somewhere) or
a genuine load spike beyond `max_size=20`. Check whether request volume
actually increased before raising the pool size.

### `RiskRejectionRateSpike`
Often benign during a regime shift (regime_detection genuinely says
"don't trade now"). Worth a look if it's sustained for hours, since it could
also mean a strategy or eligibility config bug is generating intents the risk
engine correctly rejects but at high volume.

### `MLModelDriftBreach`
8011 only logs + gauges on drift — it will not retrain itself. This alert
*is* the retrain trigger. Options: `POST /training/retrain-all`, or inspect
`GET /features/{symbol}/drift` first to decide if it's a real distribution
shift or a temporary data quality blip (e.g. a bad print from market_data).

### `BacktestJobStuckRunning`
Known limitation: no crash-recovery reconciliation in 8010. Manually check
`bt_runs` for the job's actual state and either re-trigger or mark it failed
directly in Postgres if the worker process is confirmed dead.

### `AIAnalystRateLimiterFailOpen`
Means LLM cost exposure is currently uncapped (Redis is down so neither rate
limiting nor caching is enforced). Restore Redis. If sustained, consider
manually pausing 8012's traffic at the gateway/dashboard level until resolved.
