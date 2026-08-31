# Portfolio Management Service — 8009

SG Trading Platform · Python 3.12 · FastAPI · asyncpg · Redis pub/sub

## Role in the Pipeline

```
execution_engine (8008)
  └─ sg:executions:{symbol}  ──►  portfolio_management (8009)  ──►  sg:portfolio:events
                                        │
                                        ├── GET /portfolio/snapshot   ◄── risk_engine (8007)
                                        ├── GET /portfolio/positions
                                        ├── GET /portfolio/exposure
                                        ├── GET /performance/{window}
                                        └── GET /ledger/trades
```

**8009 is the canonical source of truth for position and portfolio state.**
`risk_engine_service` (8007) should call `GET /api/v1/portfolio/snapshot` here,
not `broker_service` (8003).

---

## Responsibilities

| Concern | Detail |
|---|---|
| **Position tracking** | Net quantity per symbol, FIFO lot ledger, avg cost basis |
| **P&L** | Realized (FIFO lot consumption), unrealized (MTM), day P&L |
| **Mark-to-market** | Background loop every `MTM_REFRESH_INTERVAL_SECONDS` (default 5s) |
| **Exposure** | Gross, net, per-symbol weight |
| **Performance metrics** | Sharpe, Sortino, Calmar, max drawdown, win rate, alpha/beta vs NIFTY50 |
| **Portfolio snapshots** | Periodic persistence to `pm_snapshots`, on-demand via REST |
| **Trade ledger** | Immutable fill event log (`pm_trade_ledger`) |
| **Benchmark comparison** | NIFTY50 by default (configurable via `BENCHMARK_SYMBOL`) |

---

## Architecture

### Fill Processing (FIFO)

Every `ORDER_FILLED` / `ORDER_PARTIALLY_FILLED` event from `sg:executions:*` is:

1. **Idempotency-checked** via `pm_processed_events` — duplicate Redis delivery is a no-op.
2. **Applied to position**: buy → open new lot → recompute avg cost; sell → consume lots FIFO → compute realized P&L.
3. **Persisted atomically**: position upsert + lot insert/update + lot consumption + trade ledger entry in one transaction.

### Mark-to-Market

- Background task runs every `MTM_REFRESH_INTERVAL_SECONDS`.
- Calls `GET /symbols/{symbol}/ltp` on `market_data_service` (8002).
- On LTP failure: uses last known price from DB (degrades gracefully, never crashes).
- Prometheus gauges `portfolio_unrealized_pnl_inr`, `portfolio_total_value_inr`, `portfolio_open_positions` updated each cycle.

### Performance Metrics

Computed from `pm_daily_returns` (NAV per trading day) using numpy:

- **Sharpe**: `mean(excess_returns) / std(excess_returns) * sqrt(252)`
- **Sortino**: same but denominator uses downside std only
- **Calmar**: `annualized_return / max_drawdown`
- **Max drawdown**: computed from rolling peak of NAV series
- **Alpha / Beta**: OLS regression of portfolio vs benchmark returns
- **Information ratio**: `mean(active_returns) / std(active_returns) * sqrt(252)`

### Database Tables (all `pm_` prefixed)

| Table | Purpose |
|---|---|
| `pm_portfolio_config` | Single-row: initial capital, cash balance |
| `pm_positions` | Net position per symbol (upserted on each fill/MTM) |
| `pm_lots` | FIFO lot ledger — one row per buy fill |
| `pm_lot_consumptions` | Sell-side audit: which lots were consumed, realized P&L |
| `pm_trade_ledger` | Immutable fill event log |
| `pm_daily_returns` | Daily NAV for performance metrics |
| `pm_snapshots` | Point-in-time portfolio snapshots |
| `pm_processed_events` | Idempotency guard for ExecutionEvent delivery |

---

## API Reference

### Portfolio

```
GET /api/v1/portfolio/snapshot            # authoritative snapshot (risk_engine calls this)
GET /api/v1/portfolio/positions           # all open positions
GET /api/v1/portfolio/positions/{symbol}  # single symbol
GET /api/v1/portfolio/exposure            # gross/net/per-symbol breakdown
GET /api/v1/portfolio/lots/{symbol}       # FIFO lot detail (tax/audit)
```

### Performance

```
GET /api/v1/performance/summary           # quick 1d / 30d / 252d summary
GET /api/v1/performance/{window}          # 1d | 7d | 30d | 90d | 252d | inception
```

### Trade Ledger / History

```
GET /api/v1/ledger/trades                 # immutable fill event log
GET /api/v1/ledger/snapshots              # historical snapshot index
GET /api/v1/ledger/snapshots/latest       # most recent full snapshot
```

### Streaming

```
GET /api/v1/portfolio/stream              # SSE — live portfolio events
```

### Observability

```
GET /api/v1/health                        # liveness + DB check
GET /metrics                              # Prometheus
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | *(required)* | asyncpg DSN to sg_db |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `REDIS_EXECUTIONS_PATTERN` | `sg:executions:*` | Fill event subscription pattern |
| `REDIS_PORTFOLIO_EVENTS_CHANNEL` | `sg:portfolio:events` | Outbound event channel |
| `MARKET_DATA_SERVICE_URL` | `http://market_data_service:8002` | LTP + benchmark prices |
| `MTM_REFRESH_INTERVAL_SECONDS` | `5` | MTM background loop interval |
| `SNAPSHOT_INTERVAL_SECONDS` | `60` | Snapshot persistence interval |
| `BENCHMARK_SYMBOL` | `NIFTY50` | Benchmark for alpha/beta |
| `AUTH_JWT_PUBLIC_KEY_PATH` | `""` | RS256 public key from auth_service (8001) |

---

## Running

```bash
# Development
cp .env.example .env
# Edit DATABASE_URL and REDIS_URL
pip install .
uvicorn app.main:app --port 8009 --reload

# Docker
docker build -t portfolio_management_service .
docker run -p 8009:8009 --env-file .env portfolio_management_service
```

## Tests

```bash
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

---

## Open Items / Known Assumptions

1. **`/symbols/{symbol}/ltp` on market_data_service (8002)** — same unconfirmed assumption as 8008. If 8002 exposes prices only via Redis candle stream, change `app/services/market_data_client.py` only.
2. **`/symbols/{symbol}/history` for benchmark series** — assumed REST endpoint. If unavailable, benchmark metrics (alpha, beta, information ratio) return `null` gracefully.
3. **`pm_portfolio_config` initial capital** — seeded to 0 in migration. Must be updated via the `upsert_portfolio_config` call (planned: admin endpoint or startup config injection).
4. **Day P&L** — approximated from intraday MTM delta. A proper SOD price snapshot per symbol would improve accuracy.
5. **Win rate / profit factor** — count-only in v1; requires `realized_pnl_inr` column in `pm_trade_ledger` (migration 002) to compute accurately.
6. **risk_engine client repoint** — `risk_engine_service` (8007) `BrokerServiceClient` must be updated to call `http://portfolio_management_service:8009/api/v1/portfolio/snapshot` instead of `broker_service:8003/portfolio/snapshot`.
