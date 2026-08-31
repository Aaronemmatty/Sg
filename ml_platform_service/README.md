# ML Platform Service — 8011

SG Trading Platform · Python 3.12 · FastAPI · XGBoost · LightGBM · LSTM · Transformer

## Role in the Pipeline

```
sg:market:candle:*  ──►  ml_platform (8011)
                              │
                              ├── feature engineering (TA indicators)
                              ├── ensemble prediction (XGB + LGBM + LSTM + Transformer)
                              │
                              ├── sg:ml:signals:{symbol}  ──►  strategy_service (8004)
                              └── sg:ml:regime:{symbol}   ──►  regime_detection (8005)

risk_engine (8007) / orchestrator (8006) → GET /predict/{symbol} (on-demand REST)
```

---

## Architecture

### Feature Store
- Real-time: FeatureVector computed on each candle, cached in Redis (TTL=30s)
- Historical: snapshots persisted to `ml_feature_snapshots` (PostgreSQL) for training
- 40+ features: returns, SMA/EMA, RSI, MACD, Stochastic, ATR, Bollinger Bands, realized vol, OBV, VWAP, price structure, regime context, time features

### Training Pipeline
Four model families, all with Optuna hyperparameter search:

| Model | Library | Fallback |
|---|---|---|
| XGBoost | xgboost | — |
| LightGBM | lightgbm | — |
| LSTM | PyTorch | sklearn MLP |
| Transformer | PyTorch | sklearn GBT |

Training lifecycle per model:
1. Load features from feature store
2. Compute targets (direction / return / volatility)
3. StandardScaler fit on train split only (temporal — no shuffle)
4. Optuna search (default 20 trials, TPE sampler)
5. Final fit on train+val
6. Evaluate on held-out test set
7. Save artifact to disk (joblib / torch.save)
8. Log to MLflow (params, metrics, artifact path)
9. Register ModelVersion in DB
10. Auto-promote if challenger beats champion by ≥0.5%

### Model Registry
- One **champion** per (symbol, model_type) — enforced by DB unique index
- Challengers evaluated against champions on val_metric
- Manual promote/retire via REST API (role-gated: `ml_engineer`)
- In-memory serving cache evicted on promotion

### Serving / Ensemble
- Champion models loaded on first predict call per (symbol, model_type), cached in-memory
- Ensemble weighting: `vote_weight = val_metric × confidence` per model
- Confidence threshold (default 0.55) gates signal publishing
- Prediction cache in Redis (TTL=60s) for repeated calls

### Monitoring
- **Drift**: PSI (Population Stability Index) per feature, computed every 30min
  - PSI < 0.1 = no drift, 0.1–0.2 = minor, > 0.2 = significant (alert + log)
- **Accuracy**: rolling directional accuracy over last 50 predictions with outcomes
  - Below 48% → warning log (future: auto-retrain trigger)
- **Retraining**: daily background loop retrains all champion models after market hours

---

## API Reference

### Training
```
POST /api/v1/training/jobs          # submit training job (ml_engineer role)
GET  /api/v1/training/jobs          # list jobs
GET  /api/v1/training/jobs/{id}     # single job
GET  /api/v1/training/active        # running jobs
POST /api/v1/training/retrain-all   # retrain all champions (ml_engineer role)
```

### Registry
```
GET  /api/v1/registry/models            # list versions
GET  /api/v1/registry/champions         # current champion per symbol
GET  /api/v1/registry/models/{id}       # single version
POST /api/v1/registry/promote/{id}      # promote to champion (ml_engineer)
POST /api/v1/registry/retire/{id}       # retire model (ml_engineer)
```

### Predictions & Features
```
POST /api/v1/predict/{symbol}           # ensemble prediction (on-demand)
POST /api/v1/predict/{symbol}/{model}   # single model prediction
GET  /api/v1/predict/history            # prediction log
GET  /api/v1/features/{symbol}          # latest cached feature vector
POST /api/v1/features/{symbol}/refresh  # force feature recomputation
GET  /api/v1/features/{symbol}/drift    # latest drift report
POST /api/v1/outcomes                   # record actual outcome for accuracy tracking
```

### Experiments (MLflow)
```
GET /api/v1/experiments/              # list experiments
GET /api/v1/experiments/runs          # list runs
GET /api/v1/experiments/runs/{id}     # single run
GET /api/v1/experiments/compare       # compare metric across runs
```

### Monitoring
```
GET  /api/v1/monitoring/accuracy        # rolling accuracy all champions
GET  /api/v1/monitoring/drift           # drift summary + alerts
GET  /api/v1/monitoring/health          # platform health check
POST /api/v1/monitoring/drift/compute   # trigger drift computation
```

### Observability
```
GET /api/v1/health    # liveness + DB check
GET /metrics          # Prometheus
```

---

## Redis Channels

| Channel | Direction | Consumer |
|---|---|---|
| `sg:market:candle:*` | inbound | CandleConsumer |
| `sg:ml:signals:{symbol}` | outbound | strategy_service (8004) |
| `sg:ml:regime:{symbol}` | outbound | regime_detection (8005) |

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | required | asyncpg DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | |
| `MARKET_DATA_SERVICE_URL` | `http://market_data_service:8002` | OHLCV source |
| `FEATURE_LOOKBACK_BARS` | `500` | bars fetched per feature computation |
| `FEATURE_CACHE_TTL_SECONDS` | `30` | Redis feature cache TTL |
| `TRAIN_MIN_SAMPLES` | `1000` | min feature snapshots to trigger training |
| `SERVING_CONFIDENCE_THRESHOLD` | `0.55` | min confidence to publish signal |
| `MODEL_ARTIFACTS_PATH` | `/var/ml_platform/models` | model file storage |
| `MLFLOW_TRACKING_URI` | `sqlite:///var/ml_platform/mlflow.db` | MLflow backend |
| `MODEL_CHAMPION_AUTO_PROMOTE` | `true` | auto-promote better challengers |

---

## Running

```bash
cp .env.example .env
# Set DATABASE_URL and REDIS_URL
pip install .
uvicorn app.main:app --port 8011 --reload

# Docker
docker build -t ml_platform_service .
docker run -p 8011:8011 --env-file .env ml_platform_service
```

## Tests

```bash
pytest tests/ -v
# 96 tests: 61 unit, 35 integration
```

---

## Open Items

1. **OHLCV REST endpoint shape** — assumed `GET /symbols/{symbol}/candles?limit=N&interval=1d` returning `{"candles": [...]}`. Same unconfirmed assumption as 8008/8009. Isolated to `app/services/market_data_client.py`.
2. **PyTorch** — LSTM and Transformer fall back to sklearn MLP / GBT when torch is unavailable. In production: `pip install torch>=2.2` to enable the full implementations.
3. **Win-rate / profit factor on signals** — `sharpe_on_signals` column in model registry is computed null in v1. Requires backtesting engine (8010) to fill in signal-level Sharpe.
4. **Auto-retrain trigger** — drift monitor and accuracy monitor log warnings but do not automatically submit new training jobs. The scheduled daily loop handles batch retraining. Event-driven retraining on drift is a v2 extension.
5. **Backtesting dependency** — ML platform is fully independent of 8010. When 8010 is built, it should read `ml_feature_snapshots` directly and can populate `sharpe_on_signals` via `POST /api/v1/registry/promote/{version_id}` after backtest evaluation.
