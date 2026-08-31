# backtesting_engine_service (8010)

Institutional-grade strategy backtesting for the SG Trading Platform.

## Decisions made for this build

Per the handover prompt's open questions (delegated to "best judgement"):

1. **Historical data source** — REST call to `market_data_service` (8002)
   `GET /symbols/{symbol}/history` as primary source, with automatic
   fallback to a local Postgres cache (`bt_ohlcv_cache`) if the REST call
   fails or is empty. Every successful REST fetch opportunistically
   populates the cache, so the fallback gets more useful over time. This
   mirrors the isolated-client pattern used by `market_data_client.py` in
   `portfolio_management_service` (8009) — same unconfirmed-contract caveat
   applies, isolated to `app/services/data_loader.py`.

2. **Strategy supply** — both modes supported via `StrategyRef.source`:
   - `registry`: calls `strategy_service` (8004)
     `POST /api/v1/strategies/{name}/evaluate` (contract assumption,
     isolated in `app/services/strategy_loader.py::RegistryStrategyProvider`).
   - `inline`: a constrained, declarative rule engine (SMA/EMA/RSI
     indicators, gt/lt/gte/lte/eq/cross_above/cross_below conditions) that
     runs locally with **no 8004 dependency and no arbitrary code
     execution** — safe to accept directly from API callers.

3. **Concurrency model** — bounded `asyncio.Semaphore` (default 3 concurrent
   backtests, `MAX_CONCURRENT_BACKTESTS`) inside the FastAPI process itself,
   not an external job queue. Appropriate for a single-node personal
   deployment; job state is persisted to Postgres (`bt_runs` + related
   tables) so results survive process restarts. A run left `RUNNING` after
   a crash is not auto-reconciled — flagged as a known limitation below.

## Features delivered

- **Historical replay** — event-driven, bar-by-bar engine
  (`app/services/backtest_engine.py`). Signals generated on bar *i* fill at
  bar *i+1*'s open — no look-ahead bias.
- **Multi-timeframe support** — `additional_timeframes` on `BacktestConfig`
  are loaded and merge-asof aligned onto the primary timeframe as
  `htf_{tf}_close` columns, ready for strategies that want higher-timeframe
  context.
- **Transaction costs & slippage** — commission (bps + fixed), and three
  slippage models (`fixed_bps`, `volume_scaled`, `spread_proxy`).
- **Walk-forward analysis** — rolling or anchored/expanding windows
  (`app/services/walk_forward.py`), with an out-of-sample consistency score.
- **Monte Carlo testing** — trade-reshuffle, return-bootstrap, and
  block-bootstrap methods, with confidence-interval percentiles,
  probability of loss, and probability of ruin (`app/services/monte_carlo.py`).
- **Performance metrics** — Sharpe, Sortino, Calmar, max drawdown (+
  duration), annualised volatility, win rate, profit factor, expectancy,
  alpha/beta/information ratio vs NIFTY50 (`app/services/performance_engine.py`).
- **Reporting** — self-contained HTML report
  (`GET /backtest/{id}/report`) plus chart-ready JSON endpoints for a
  dashboard to render (`/chart/equity`, `/chart/trades`, `/chart/monte-carlo`).
- **REST API** exactly as specified: `POST /backtest/run`,
  `GET /backtest/{id}/results`, `GET /backtest/{id}/trades`,
  `GET /backtest/{id}/equity-curve`, plus list/cancel/walk-forward/monte-carlo
  convenience endpoints.
- Matches all platform conventions: structlog, OTel, Prometheus, asyncpg,
  Pydantic v2, hatchling, JWT RS256 (dev stub fallback identical to other
  services).

## Known limitations / open items for next session

1. **Walk-forward is not a true optimiser.** In-sample metrics are the same
   strategy config re-run on the train slice — useful for measuring
   consistency over time, but there is no parameter re-fitting between
   windows. A future optimiser would slot into `walk_forward.py::_run_slice`.
2. **Annualisation factor is fixed at 252 bars/year** in
   `performance_engine.py` regardless of the configured timeframe. Correct
   for daily backtests; intraday timeframes will under/overstate Sharpe et
   al. until a timeframe-aware factor is wired in.
3. **`market_data_service` history contract is unconfirmed** (inherited
   open item from 8008/8009): assumed
   `GET /symbols/{symbol}/history?start&end&interval` → `{"candles": [...]}`.
   Isolated to `data_loader.py` — confirm against the real 8002 contract.
4. **`strategy_service` evaluate contract is unconfirmed and new** — assumed
   `POST /api/v1/strategies/{name}/evaluate`. This wasn't previously
   established by any built service; confirm strategy_service actually
   exposes something like this before relying on `source=registry` in
   production. `source=inline` has no such dependency and is safe today.
5. **Crash recovery** — a run stuck in `RUNNING` after a process crash is
   not automatically requeued or marked `FAILED`. Add a startup
   reconciliation pass if this matters for the deployment.
6. **RSI uses a simple rolling-mean smoothing**, not Wilder's smoothing —
   close enough for rule-based entries but not identical to most charting
   platforms' RSI.

## Running locally

```bash
pip install -e ".[dev]"
cp .env.example .env   # point DATABASE_URL at your sg_db instance
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

> Note: this sandbox has no network access, so the test suite above was
> written carefully and manually traced through but **could not be executed
> here**. Please run `pytest` in your actual dev environment (which already
> has these exact dependencies installed for 8001–8009) before declaring
> this service complete, per the platform rule that all tests must pass.
