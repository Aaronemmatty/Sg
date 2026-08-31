# regime_detection_service (Port 8005)

Market Regime Detection Engine for the SG Algorithmic Trading Platform.

Classifies current market conditions (TRENDING, RANGING, HIGH_VOLATILITY, LOW_VOLATILITY,
RISK_ON, RISK_OFF, BULLISH, BEARISH, SIDEWAYS) for NIFTY50 (market-wide, primary) and
per-symbol (override, fires only on divergence from the index), on every completed 5-minute
candle, using a hybrid technical-feature + sklearn-classifier approach with a pure rule-based
fallback when no trained model is loaded.

## Integration assumptions (adjust to match your real `sg_db` package)

This service is written to slot into the existing platform conventions described in the
project brief:

- `sg_db` already provides shared SQLAlchemy declarative `Base`, `TimestampMixin`,
  `SoftDeleteMixin`, a UUID PK helper, and a tenant-scoped RLS mixin. This service imports
  them from `sg_db.common` (`from sg_db.common import Base, TimestampMixin, SoftDeleteMixin,
  TenantMixin, uuid_pk`). **If your actual package exposes these under different module
  paths, update `app/models/db.py` imports accordingly** — nothing else depends on the path.
- `sg_db.market_data.MarketBar` is the existing partitioned OHLCV table. This service reads
  from it for historical features/backtests via `app/services/market_data_client.py`.
  Update the import path / column names there if they differ from your schema.
- `market_data_service` (port 8002) is the live source of truth; this service prefers Redis
  (`candle:{symbol}:{timeframe}`, pub/sub `sg:market:candle:{symbol}:{tf}`) for live data and
  only falls back to direct DB/REST reads for backfill and warm-up windows.
- Auth: internal-only service. Endpoints expect the platform's standard JWT (RS256) bearer
  token validated via the shared `auth_service` public key (see `app/core/security.py`
  stub) — wire in your existing dependency from `auth_service`'s shared client lib if one
  exists; a minimal local verifier is included so the service is runnable standalone.

## Run locally

```bash
docker compose up --build
# or
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8005
```

## Train the optional ML classifier

```bash
python -m app.services.training.train_classifier --symbol NIFTY50 --timeframe 5m \
    --lookback-days 730 --out models/regime_classifier.joblib
```

Without a model present at `REGIME_MODEL_PATH`, the service runs entirely on the
rule-based classifier (`app/core/classifier.py::RuleBasedClassifier`) — fully functional,
just less adaptive than the trained hybrid.

## Folder structure

```
regime_detection_service/
  app/
    main.py                       FastAPI app, lifespan, /health /ready /metrics
    config.py                     Settings (env-driven)
    api/v1/
      regime.py                   REST endpoints
      websocket.py                Real-time regime stream
      schemas.py                  Request/response models (API-facing)
    core/
      features.py                 Technical feature engineering (ADX, ATR, BB width, ...)
      classifier.py                RuleBasedClassifier, MLClassifier, HybridClassifier
      breadth.py                   Market breadth (advance/decline, RISK_ON/OFF)
      engine.py                    RegimeDetectionEngine orchestrator
      transitions.py               Change detection, debouncing, alerts
      security.py                  JWT verification stub
    models/
      domain.py                    Pydantic domain models (engine-internal contracts)
      db.py                        sg_db-style SQLAlchemy models (regime_snapshots, ...)
    services/
      redis_client.py              Redis cache + pub/sub wrapper
      candle_consumer.py            Subscribes to candle events, drives recalculation
      market_data_client.py        Historical OHLCV access (DB + market_data_service)
      backtest_service.py          Historical regime replay
      training/
        dataset.py                 Feature/label dataset construction
        train_classifier.py        Offline training CLI
    db/
      session.py                   Async SQLAlchemy session/engine
      migrations/                  Alembic env + versions
    events/
      contracts.py                  Pydantic event schemas
      publisher.py                  Publishes to sg:regime:{symbol}
    workers/
      scheduler.py                  5-min watchdog recompute (redundant to candle events)
  tests/
    unit/                          Pure-function and class unit tests
    integration/                   API + Redis + pipeline tests
  models/                          Trained classifier artifacts (gitignored)
  Dockerfile
  requirements.txt
  alembic.ini
  pytest.ini
  .env.example
```
