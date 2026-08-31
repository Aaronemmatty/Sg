# signal_aggregation_service (Port 8006)

Signal Aggregation Engine for the SG Trading Platform. Combines per-strategy signals
(Trend Following, Mean Reversion, Breakout, Momentum, ML Prediction, and any Custom
strategy) plus the current market regime (from `regime_detection_service`, port 8005)
into one consensus opinion per symbol/timeframe.

## Locked decisions (this build)

- **Trigger**: event-driven — recomputes whenever a new strategy signal is published on
  `sg:signals:{symbol}` **or** the regime changes on `sg:regime:{symbol}` (a regime flip
  changes which weights apply, so it deserves its own recompute) — **plus** a 5-minute
  watchdog that recomputes any symbol whose cached aggregate is missing or stale, mirroring
  `regime_detection_service`'s reliability pattern.
- **Conflict resolution**: weighted net directional score against a configurable threshold
  (`net_score = Σ effective_weight_i × direction_i × confidence_i`), where weights are
  **renormalized at compute time** over only the strategies that actually reported (a
  missing ML signal doesn't silently zero out the vote). Final confidence is the net
  score's magnitude, **dampened by an agreement ratio** (how much of the voting weight
  agrees with the winning direction) and **capped when too few strategies contributed**.
  This is more robust and explainable than plain plurality voting or a hard veto rule,
  while still letting one very strong, very confident strategy carry a thin market.
- **Weights**: static regime→strategy defaults in code (matching the example in the brief)
  layered with DB-backed, hot-reloadable overrides (`strategy_weight_overrides` table +
  `/api/v1/weights` CRUD), cached in Redis and invalidated via the `sg:weights:updated`
  pub/sub channel so a weight change takes effect on the next recompute without a restart.

## New Redis conventions introduced by this service

```
aggregated_signal:{symbol}:{timeframe}   → latest AggregatedSignalResult (cache)
sg:aggregated_signal:{symbol}            → pub/sub: published on every recompute
sg:weights:updated                       → pub/sub: invalidates the in-process weight cache
```

## Integration assumptions

- **Strategy signal input**: reads `signal:{strategy}:{symbol}:{tf}` (per the platform's
  existing Redis convention) for the latest signal from each strategy, and treats
  `sg:signals:{symbol}` events as `{"strategy": ..., "symbol": ..., "timeframe": ...,
  "action": "BUY"|"SELL"|"HOLD", "confidence": 0-1, "timestamp": ...}`. If your
  `strategy_service` publishes a different shape, only `app/core/normalization.py` and
  `app/services/redis_client.py::get_strategy_signal` need to change.
- **Strategy discovery**: a configured `STRATEGY_REGISTRY` provides default weight-mapping
  names (`trend_following`, `mean_reversion`, `breakout`, `momentum`, `ml_prediction`,
  `rsi`), but at aggregation time the engine also `SCAN`s for any `signal:*:{symbol}:{tf}`
  key, so genuinely custom/unregistered strategies are still collected and voted on (with a
  configurable, conservative default weight) rather than silently ignored.
- **Regime input**: reads `regime:{symbol}:{timeframe}` exactly as written by
  `regime_detection_service` (full `RegimeResult`-shaped JSON) — no changes needed if
  deployed alongside it.
- **sg_db**: same `Base`/`TimestampMixin`/`SoftDeleteMixin`/`TenantMixin` convention as
  `regime_detection_service`, imported from `sg_db.common` with the same standalone
  fallback in `app/db/_sg_db_compat.py` if that import isn't available in your environment.
- **Auth**: same RS256 bearer-token verification stub as `regime_detection_service`
  (`app/core/security.py`) — wire in the shared client from `auth_service` if one exists.

## Run locally

```bash
docker compose up --build
# or
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8006
```

## Folder structure

```
signal_aggregation_service/
  app/
    main.py                      FastAPI app, lifespan, /health /ready /metrics
    config.py                    Settings + static default regime→strategy weight tables
    api/v1/
      aggregation.py             REST endpoints (signal, history, weights CRUD, recalc)
      schemas.py
      websocket.py               Real-time aggregated-signal stream
    core/
      normalization.py           Raw strategy payload -> canonical SignalVote
      weighting.py                WeightingEngine: regime+strategy -> effective weight
      confidence.py                ConfidenceEngine: net score, agreement, final confidence
      conflict.py                  ConflictResolutionEngine: BUY/SELL/HOLD decision + contributors
      engine.py                    SignalAggregationEngine orchestrator
      security.py
    models/
      domain.py                    Pydantic domain models (engine-internal + API contracts)
      db.py                        sg_db-style models: aggregated_signals, weight overrides
    services/
      redis_client.py              Redis cache + pub/sub + SCAN-based strategy discovery
      signal_consumer.py           Event-driven trigger (signals + regime channels)
      weight_store.py              DB-backed weight override CRUD + cache + invalidation
    db/
      session.py
      migrations/
    events/
      contracts.py
      publisher.py
    workers/
      scheduler.py                 5-min watchdog recompute
  tests/
    unit/                          normalization, weighting, confidence, conflict, engine
    integration/                   API, Redis pub/sub, full pipeline
  Dockerfile
  requirements.txt
  alembic.ini
  pytest.ini
  .env.example
```
