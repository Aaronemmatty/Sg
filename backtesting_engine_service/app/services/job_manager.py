from __future__ import annotations

import asyncio
import time
import traceback
import uuid

import asyncpg
import pandas as pd

from app.core.config import settings
from app.core.logging import log
from app.core.metrics import (
    ACTIVE_BACKTESTS,
    BACKTEST_DURATION_SECONDS,
    BACKTESTS_COMPLETED,
    BACKTESTS_STARTED,
)
from app.db.repository import BacktestRepository
from app.models.domain import (
    BacktestConfig,
    BacktestMode,
    BacktestRunRequest,
    BacktestStatus,
    OHLCVBar,
    Timeframe,
)
from app.services.backtest_engine import BacktestEngine
from app.services.data_loader import DataLoaderError, HistoricalDataLoader
from app.services.monte_carlo import run_monte_carlo
from app.services.performance_engine import compute_performance
from app.services.strategy_loader import StrategyLoadError, build_signal_provider
from app.services.walk_forward import run_walk_forward


def bars_to_df(bars: list[OHLCVBar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(
        [
            {
                "ts": b.ts,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in bars
        ]
    )
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").drop_duplicates(subset="ts").reset_index(drop=True)


async def load_symbol_bars(
    loader: HistoricalDataLoader, symbol: str, config: BacktestConfig
) -> pd.DataFrame:
    primary = await loader.load(symbol, config.primary_timeframe, config.start_date, config.end_date)
    df = bars_to_df(primary)

    for tf in config.additional_timeframes:
        try:
            htf_bars = await loader.load(symbol, tf, config.start_date, config.end_date)
        except DataLoaderError:
            log.warning("additional_timeframe_unavailable", symbol=symbol, timeframe=tf.value)
            continue
        htf_df = bars_to_df(htf_bars)
        if htf_df.empty:
            continue
        htf_df = htf_df[["ts", "close"]].rename(columns={"close": f"htf_{tf.value}_close"})
        df = pd.merge_asof(df.sort_values("ts"), htf_df.sort_values("ts"), on="ts", direction="backward")

    return df


class JobManager:
    """Owns the asyncio-based concurrency control for backtest execution.

    Chosen over an external job queue (Redis/Celery) because this is a
    single-node personal deployment — asyncio tasks bounded by a semaphore
    give real parallelism for I/O-bound data loading and CPU-bound numpy
    work without adding infra. Job state is persisted to Postgres so it
    survives process restarts (a run left RUNNING after a crash should be
    treated as FAILED/orphaned by an external reconciler — not handled here).
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._repo = BacktestRepository(pool)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_backtests)
        self._tasks: dict[uuid.UUID, asyncio.Task] = {}

    @property
    def repo(self) -> BacktestRepository:
        return self._repo

    async def submit(
        self, request: BacktestRunRequest, auth_header: str | None = None
    ) -> uuid.UUID:
        if request.config.initial_capital_inr is None:
            from app.services.capital_provider import resolve_initial_capital

            await resolve_initial_capital(request.config, auth_header=auth_header)
        elif request.config.capital_source is None:
            request.config.capital_source = "user-override"
            log.info(
                "backtest_capital_resolved",
                run_name=request.config.name,
                initial_capital_inr=request.config.initial_capital_inr,
                source="user-override",
            )
        run_id = uuid.uuid4()
        await self._repo.create_run(
            run_id, request.mode, request.config, request.walk_forward, request.monte_carlo
        )
        task = asyncio.create_task(self._execute(run_id, request))
        self._tasks[run_id] = task
        task.add_done_callback(lambda t: self._tasks.pop(run_id, None))
        BACKTESTS_STARTED.labels(mode=request.mode.value).inc()
        return run_id

    async def cancel(self, run_id: uuid.UUID) -> bool:
        task = self._tasks.get(run_id)
        if task is None:
            return False
        task.cancel()
        await self._repo.update_status(run_id, BacktestStatus.CANCELLED)
        return True

    async def _execute(self, run_id: uuid.UUID, request: BacktestRunRequest) -> None:
        async with self._semaphore:
            ACTIVE_BACKTESTS.inc()
            start_t = time.monotonic()
            await self._repo.update_status(run_id, BacktestStatus.RUNNING, progress_pct=1.0)
            log.info("backtest_run_started", run_id=str(run_id), mode=request.mode.value)

            loader = HistoricalDataLoader(self._repo)
            try:
                config = request.config
                bars_by_symbol = {
                    sym: await load_symbol_bars(loader, sym, config) for sym in config.symbols
                }
                if all(df.empty for df in bars_by_symbol.values()):
                    raise DataLoaderError(
                        f"No historical data resolved for any of {config.symbols} "
                        f"between {config.start_date} and {config.end_date}"
                    )

                benchmark_df = None
                if config.benchmark_symbol:
                    try:
                        bench_bars = await loader.load_benchmark(
                            config.benchmark_symbol,
                            config.primary_timeframe,
                            config.start_date,
                            config.end_date,
                        )
                        benchmark_df = bars_to_df(bench_bars)
                    except DataLoaderError:
                        benchmark_df = None

                if request.mode == BacktestMode.SINGLE:
                    await self._run_single(run_id, config, bars_by_symbol, benchmark_df)
                elif request.mode == BacktestMode.WALK_FORWARD:
                    if request.walk_forward is None:
                        raise ValueError("walk_forward config is required for mode=walk_forward")
                    await self._run_walk_forward(run_id, config, request.walk_forward, bars_by_symbol, benchmark_df)
                elif request.mode == BacktestMode.MONTE_CARLO:
                    if request.monte_carlo is None:
                        raise ValueError("monte_carlo config is required for mode=monte_carlo")
                    await self._run_monte_carlo(run_id, config, request.monte_carlo, bars_by_symbol, benchmark_df)

                await self._repo.update_status(run_id, BacktestStatus.COMPLETED, progress_pct=100.0)
                BACKTESTS_COMPLETED.labels(mode=request.mode.value, status="completed").inc()
                log.info("backtest_run_completed", run_id=str(run_id))

            except asyncio.CancelledError:
                await self._repo.update_status(run_id, BacktestStatus.CANCELLED)
                BACKTESTS_COMPLETED.labels(mode=request.mode.value, status="cancelled").inc()
                raise
            except Exception as exc:  # noqa: BLE001
                tb = traceback.format_exc()
                log.error("backtest_run_failed", run_id=str(run_id), error=str(exc), traceback=tb)
                await self._repo.update_status(run_id, BacktestStatus.FAILED, error=str(exc))
                BACKTESTS_COMPLETED.labels(mode=request.mode.value, status="failed").inc()
            finally:
                await loader.aclose()
                ACTIVE_BACKTESTS.dec()
                BACKTEST_DURATION_SECONDS.labels(mode=request.mode.value).observe(
                    time.monotonic() - start_t
                )

    async def _run_single(self, run_id, config, bars_by_symbol, benchmark_df) -> None:
        provider = build_signal_provider(config.strategy)
        try:
            for sym, df in bars_by_symbol.items():
                if not df.empty:
                    await provider.prepare(sym, df)
            engine = BacktestEngine(config)
            trades, equity_curve = engine.run(bars_by_symbol, provider, benchmark_df)
            initial_cap = config.initial_capital_inr or settings.default_initial_capital_inr
            metrics = compute_performance(equity_curve, trades, initial_cap)

            await self._repo.save_trades(run_id, trades)
            await self._repo.save_equity_curve(run_id, equity_curve)
            await self._repo.save_performance(run_id, metrics)
        finally:
            await provider.aclose()

    async def _run_walk_forward(self, run_id, config, wf_config, bars_by_symbol, benchmark_df) -> None:
        result = await run_walk_forward(config, wf_config, bars_by_symbol, benchmark_df)
        await self._repo.save_walk_forward(run_id, result)

    async def _run_monte_carlo(self, run_id, config, mc_config, bars_by_symbol, benchmark_df) -> None:
        # Baseline single backtest first — Monte Carlo perturbs its trades/returns.
        provider = build_signal_provider(config.strategy)
        try:
            for sym, df in bars_by_symbol.items():
                if not df.empty:
                    await provider.prepare(sym, df)
            engine = BacktestEngine(config)
            trades, equity_curve = engine.run(bars_by_symbol, provider, benchmark_df)
        finally:
            await provider.aclose()

        await self._repo.save_trades(run_id, trades)
        await self._repo.save_equity_curve(run_id, equity_curve)
        initial_cap = config.initial_capital_inr or settings.default_initial_capital_inr
        baseline_metrics = compute_performance(equity_curve, trades, initial_cap)
        await self._repo.save_performance(run_id, baseline_metrics)

        mc_result = run_monte_carlo(mc_config, equity_curve, trades, initial_cap)
        await self._repo.save_monte_carlo(run_id, mc_result)
