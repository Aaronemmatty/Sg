from __future__ import annotations

import json
import uuid
from datetime import datetime

import asyncpg

from app.models.domain import (
    BacktestConfig,
    BacktestMode,
    BacktestRun,
    BacktestStatus,
    EquityPoint,
    MonteCarloConfig,
    MonteCarloPercentile,
    MonteCarloResult,
    OHLCVBar,
    OrderAction,
    PerformanceMetrics,
    SimulatedTrade,
    Timeframe,
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardWindowResult,
)


class BacktestRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── Runs ────────────────────────────────────────────────────────────────

    async def create_run(
        self,
        run_id: uuid.UUID,
        mode: BacktestMode,
        config: BacktestConfig,
        walk_forward_config: WalkForwardConfig | None,
        monte_carlo_config: MonteCarloConfig | None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bt_runs
                    (id, mode, status, config, walk_forward_config, monte_carlo_config)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                run_id,
                mode.value,
                BacktestStatus.PENDING.value,
                config.model_dump_json(),
                walk_forward_config.model_dump_json() if walk_forward_config else None,
                monte_carlo_config.model_dump_json() if monte_carlo_config else None,
            )

    async def update_status(
        self,
        run_id: uuid.UUID,
        status: BacktestStatus,
        error: str | None = None,
        progress_pct: float | None = None,
    ) -> None:
        sets = ["status = $2"]
        params: list = [run_id, status.value]
        idx = 3
        if error is not None:
            sets.append(f"error = ${idx}")
            params.append(error)
            idx += 1
        if progress_pct is not None:
            sets.append(f"progress_pct = ${idx}")
            params.append(progress_pct)
            idx += 1
        if status == BacktestStatus.RUNNING:
            sets.append("started_at = now()")
        if status in (BacktestStatus.COMPLETED, BacktestStatus.FAILED, BacktestStatus.CANCELLED):
            sets.append("completed_at = now()")

        sql = f"UPDATE bt_runs SET {', '.join(sets)} WHERE id = $1"
        async with self._pool.acquire() as conn:
            await conn.execute(sql, *params)

    async def get_run(self, run_id: uuid.UUID) -> BacktestRun | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM bt_runs WHERE id = $1", run_id)
        if row is None:
            return None
        return self._row_to_run(row)

    async def list_runs(self, limit: int = 50, offset: int = 0) -> list[BacktestRun]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bt_runs ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                limit,
                offset,
            )
        return [self._row_to_run(r) for r in rows]

    @staticmethod
    def _row_to_run(row: asyncpg.Record) -> BacktestRun:
        config = BacktestConfig.model_validate_json(row["config"])
        wf = (
            WalkForwardConfig.model_validate_json(row["walk_forward_config"])
            if row["walk_forward_config"]
            else None
        )
        mc = (
            MonteCarloConfig.model_validate_json(row["monte_carlo_config"])
            if row["monte_carlo_config"]
            else None
        )
        return BacktestRun(
            id=row["id"],
            mode=BacktestMode(row["mode"]),
            status=BacktestStatus(row["status"]),
            config=config,
            walk_forward_config=wf,
            monte_carlo_config=mc,
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            progress_pct=row["progress_pct"],
        )

    # ── Trades ───────────────────────────────────────────────────────────────

    async def save_trades(self, run_id: uuid.UUID, trades: list[SimulatedTrade]) -> None:
        if not trades:
            return
        rows = [
            (
                t.trade_id,
                run_id,
                t.symbol,
                t.action.value,
                t.entry_ts,
                t.entry_price_inr,
                t.exit_ts,
                t.exit_price_inr,
                t.quantity,
                t.commission_inr,
                t.slippage_inr,
                t.realized_pnl_inr,
                t.realized_pnl_pct,
                t.holding_period_bars,
                t.exit_reason,
            )
            for t in trades
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO bt_trades
                    (id, run_id, symbol, action, entry_ts, entry_price_inr, exit_ts,
                     exit_price_inr, quantity, commission_inr, slippage_inr,
                     realized_pnl_inr, realized_pnl_pct, holding_period_bars, exit_reason)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
                """,
                rows,
            )

    async def get_trades(self, run_id: uuid.UUID) -> list[SimulatedTrade]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bt_trades WHERE run_id = $1 ORDER BY entry_ts", run_id
            )
        return [
            SimulatedTrade(
                trade_id=r["id"],
                symbol=r["symbol"],
                action=OrderAction(r["action"]),
                entry_ts=r["entry_ts"],
                entry_price_inr=r["entry_price_inr"],
                exit_ts=r["exit_ts"],
                exit_price_inr=r["exit_price_inr"],
                quantity=r["quantity"],
                commission_inr=r["commission_inr"],
                slippage_inr=r["slippage_inr"],
                realized_pnl_inr=r["realized_pnl_inr"],
                realized_pnl_pct=r["realized_pnl_pct"],
                holding_period_bars=r["holding_period_bars"],
                exit_reason=r["exit_reason"],
            )
            for r in rows
        ]

    # ── Equity curve ─────────────────────────────────────────────────────────

    async def save_equity_curve(self, run_id: uuid.UUID, points: list[EquityPoint]) -> None:
        if not points:
            return
        rows = [
            (run_id, p.ts, p.equity_inr, p.cash_inr, p.drawdown_pct, p.benchmark_equity_inr)
            for p in points
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO bt_equity_curve
                    (run_id, ts, equity_inr, cash_inr, drawdown_pct, benchmark_equity_inr)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (run_id, ts) DO UPDATE SET
                    equity_inr = EXCLUDED.equity_inr,
                    cash_inr = EXCLUDED.cash_inr,
                    drawdown_pct = EXCLUDED.drawdown_pct,
                    benchmark_equity_inr = EXCLUDED.benchmark_equity_inr
                """,
                rows,
            )

    async def get_equity_curve(self, run_id: uuid.UUID) -> list[EquityPoint]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM bt_equity_curve WHERE run_id = $1 ORDER BY ts", run_id
            )
        return [
            EquityPoint(
                ts=r["ts"],
                equity_inr=r["equity_inr"],
                cash_inr=r["cash_inr"],
                drawdown_pct=r["drawdown_pct"],
                benchmark_equity_inr=r["benchmark_equity_inr"],
            )
            for r in rows
        ]

    # ── Performance ──────────────────────────────────────────────────────────

    async def save_performance(self, run_id: uuid.UUID, metrics: PerformanceMetrics) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bt_performance (run_id, metrics)
                VALUES ($1, $2)
                ON CONFLICT (run_id) DO UPDATE SET metrics = EXCLUDED.metrics, computed_at = now()
                """,
                run_id,
                metrics.model_dump_json(),
            )

    async def get_performance(self, run_id: uuid.UUID) -> PerformanceMetrics | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT metrics FROM bt_performance WHERE run_id = $1", run_id
            )
        if row is None:
            return None
        return PerformanceMetrics.model_validate_json(row["metrics"])

    # ── Walk-forward ─────────────────────────────────────────────────────────

    async def save_walk_forward(self, run_id: uuid.UUID, result: WalkForwardResult) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM bt_walk_forward_windows WHERE run_id = $1", run_id
                )
                for w in result.windows:
                    await conn.execute(
                        """
                        INSERT INTO bt_walk_forward_windows
                            (id, run_id, window_index, train_start, train_end,
                             test_start, test_end, in_sample_metrics, out_sample_metrics)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                        """,
                        uuid.uuid4(),
                        run_id,
                        w.window_index,
                        w.train_start,
                        w.train_end,
                        w.test_start,
                        w.test_end,
                        w.in_sample_metrics.model_dump_json(),
                        w.out_sample_metrics.model_dump_json(),
                    )
                await conn.execute(
                    """
                    INSERT INTO bt_walk_forward_summary
                        (run_id, aggregate_out_sample_metrics, consistency_score_pct)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (run_id) DO UPDATE SET
                        aggregate_out_sample_metrics = EXCLUDED.aggregate_out_sample_metrics,
                        consistency_score_pct = EXCLUDED.consistency_score_pct
                    """,
                    run_id,
                    result.aggregate_out_sample_metrics.model_dump_json(),
                    result.consistency_score_pct,
                )

    async def get_walk_forward(self, run_id: uuid.UUID) -> WalkForwardResult | None:
        async with self._pool.acquire() as conn:
            summary = await conn.fetchrow(
                "SELECT * FROM bt_walk_forward_summary WHERE run_id = $1", run_id
            )
            if summary is None:
                return None
            window_rows = await conn.fetch(
                "SELECT * FROM bt_walk_forward_windows WHERE run_id = $1 ORDER BY window_index",
                run_id,
            )
        windows = [
            WalkForwardWindowResult(
                window_index=r["window_index"],
                train_start=r["train_start"],
                train_end=r["train_end"],
                test_start=r["test_start"],
                test_end=r["test_end"],
                in_sample_metrics=PerformanceMetrics.model_validate_json(r["in_sample_metrics"]),
                out_sample_metrics=PerformanceMetrics.model_validate_json(r["out_sample_metrics"]),
            )
            for r in window_rows
        ]
        return WalkForwardResult(
            windows=windows,
            aggregate_out_sample_metrics=PerformanceMetrics.model_validate_json(
                summary["aggregate_out_sample_metrics"]
            ),
            consistency_score_pct=summary["consistency_score_pct"],
        )

    # ── Monte Carlo ──────────────────────────────────────────────────────────

    async def save_monte_carlo(self, run_id: uuid.UUID, result: MonteCarloResult) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bt_monte_carlo_results
                    (run_id, iterations, method, percentiles, probability_of_loss_pct,
                     probability_of_ruin_pct, original_metrics, median_metrics)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (run_id) DO UPDATE SET
                    iterations = EXCLUDED.iterations,
                    method = EXCLUDED.method,
                    percentiles = EXCLUDED.percentiles,
                    probability_of_loss_pct = EXCLUDED.probability_of_loss_pct,
                    probability_of_ruin_pct = EXCLUDED.probability_of_ruin_pct,
                    original_metrics = EXCLUDED.original_metrics,
                    median_metrics = EXCLUDED.median_metrics
                """,
                run_id,
                result.iterations,
                result.method,
                json.dumps([p.model_dump() for p in result.percentiles]),
                result.probability_of_loss_pct,
                result.probability_of_ruin_pct,
                result.original_metrics.model_dump_json(),
                result.median_metrics.model_dump_json(),
            )

    async def get_monte_carlo(self, run_id: uuid.UUID) -> MonteCarloResult | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM bt_monte_carlo_results WHERE run_id = $1", run_id
            )
        if row is None:
            return None
        percentiles_raw = json.loads(row["percentiles"])
        return MonteCarloResult(
            iterations=row["iterations"],
            method=row["method"],
            percentiles=[MonteCarloPercentile.model_validate(p) for p in percentiles_raw],
            probability_of_loss_pct=row["probability_of_loss_pct"],
            probability_of_ruin_pct=row["probability_of_ruin_pct"],
            original_metrics=PerformanceMetrics.model_validate_json(row["original_metrics"]),
            median_metrics=PerformanceMetrics.model_validate_json(row["median_metrics"]),
        )

    # ── OHLCV cache (DB fallback source) ─────────────────────────────────────

    async def get_cached_ohlcv(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[OHLCVBar]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM bt_ohlcv_cache
                WHERE symbol = $1 AND timeframe = $2 AND ts >= $3 AND ts <= $4
                ORDER BY ts
                """,
                symbol,
                timeframe.value,
                start,
                end,
            )
        return [
            OHLCVBar(
                symbol=r["symbol"],
                timeframe=Timeframe(r["timeframe"]),
                ts=r["ts"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
            )
            for r in rows
        ]

    async def cache_ohlcv(self, bars: list[OHLCVBar]) -> None:
        if not bars:
            return
        rows = [
            (b.symbol, b.timeframe.value, b.ts, b.open, b.high, b.low, b.close, b.volume)
            for b in bars
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO bt_ohlcv_cache (symbol, timeframe, ts, open, high, low, close, volume)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                ON CONFLICT (symbol, timeframe, ts) DO NOTHING
                """,
                rows,
            )
