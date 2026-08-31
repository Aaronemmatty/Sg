from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from app.models.domain import BacktestResultBundle, PerformanceMetrics, SimulatedTrade


def _metric_row(label: str, value) -> str:
    if value is None:
        value = "—"
    return f"<tr><td>{label}</td><td>{value}</td></tr>"


def _performance_table_html(m: PerformanceMetrics) -> str:
    rows = [
        _metric_row("Total Return", f"{m.total_return_pct:.2f}%"),
        _metric_row("CAGR", f"{m.cagr_pct:.2f}%" if m.cagr_pct is not None else None),
        _metric_row("Sharpe Ratio", f"{m.sharpe_ratio:.2f}" if m.sharpe_ratio is not None else None),
        _metric_row("Sortino Ratio", f"{m.sortino_ratio:.2f}" if m.sortino_ratio is not None else None),
        _metric_row("Calmar Ratio", f"{m.calmar_ratio:.2f}" if m.calmar_ratio is not None else None),
        _metric_row("Max Drawdown", f"{m.max_drawdown_pct:.2f}%"),
        _metric_row("Volatility (ann.)", f"{m.volatility_annualized_pct:.2f}%" if m.volatility_annualized_pct is not None else None),
        _metric_row("Win Rate", f"{m.win_rate_pct:.1f}%" if m.win_rate_pct is not None else None),
        _metric_row("Profit Factor", f"{m.profit_factor:.2f}" if isinstance(m.profit_factor, (int, float)) else m.profit_factor),
        _metric_row("Avg Win", f"₹{m.avg_win_inr:,.2f}" if m.avg_win_inr is not None else None),
        _metric_row("Avg Loss", f"₹{m.avg_loss_inr:,.2f}" if m.avg_loss_inr is not None else None),
        _metric_row("Expectancy / Trade", f"₹{m.expectancy_inr:,.2f}" if m.expectancy_inr is not None else None),
        _metric_row("Number of Trades", m.num_trades),
        _metric_row("Alpha", f"{m.alpha_pct:.2f}%" if m.alpha_pct is not None else None),
        _metric_row("Beta", f"{m.beta:.2f}" if m.beta is not None else None),
        _metric_row("Information Ratio", f"{m.information_ratio:.2f}" if m.information_ratio is not None else None),
        _metric_row("Final Equity", f"₹{m.final_equity_inr:,.2f}"),
    ]
    return "\n".join(rows)


_REPORT_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a2e; background: #fafafa; }
h1 { font-size: 1.6rem; margin-bottom: 0; }
.subtitle { color: #666; margin-top: 0.25rem; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; max-width: 640px; margin-bottom: 2rem; background: #fff; }
td { padding: 0.5rem 1rem; border-bottom: 1px solid #eee; }
td:first-child { color: #555; }
td:last-child { font-weight: 600; text-align: right; }
.badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; }
.badge.completed { background: #d1fae5; color: #065f46; }
.badge.failed { background: #fee2e2; color: #991b1b; }
section { margin-bottom: 2rem; }
"""


def generate_html_report(bundle: BacktestResultBundle) -> str:
    run = bundle.run
    status_class = run.status.value.lower()
    perf_html = _performance_table_html(bundle.performance) if bundle.performance else "<p>No performance data.</p>"

    walk_forward_html = ""
    if bundle.walk_forward:
        wf_rows = "".join(
            f"<tr><td>{w.window_index}</td><td>{w.train_start}–{w.train_end}</td>"
            f"<td>{w.test_start}–{w.test_end}</td>"
            f"<td>{w.in_sample_metrics.total_return_pct:.2f}%</td>"
            f"<td>{w.out_sample_metrics.total_return_pct:.2f}%</td></tr>"
            for w in bundle.walk_forward.windows
        )
        walk_forward_html = f"""
        <section>
          <h2>Walk-Forward Analysis</h2>
          <p>Consistency score (OOS windows positive): {bundle.walk_forward.consistency_score_pct:.1f}%</p>
          <table>
            <tr><td><b>#</b></td><td><b>Train</b></td><td><b>Test</b></td><td><b>IS Return</b></td><td><b>OOS Return</b></td></tr>
            {wf_rows}
          </table>
        </section>
        """

    monte_carlo_html = ""
    if bundle.monte_carlo:
        mc = bundle.monte_carlo
        pct_rows = "".join(
            f"<tr><td>{p.confidence_level * 100:.0f}th pct</td>"
            f"<td>₹{p.final_equity_inr:,.0f}</td><td>{p.total_return_pct:.2f}%</td>"
            f"<td>{p.max_drawdown_pct:.2f}%</td></tr>"
            for p in mc.percentiles
        )
        monte_carlo_html = f"""
        <section>
          <h2>Monte Carlo Simulation ({mc.iterations:,} iterations, {mc.method})</h2>
          <p>Probability of loss: {mc.probability_of_loss_pct:.1f}% &nbsp;|&nbsp;
             Probability of ruin (&lt;50% capital): {mc.probability_of_ruin_pct:.1f}%</p>
          <table>
            <tr><td><b>Percentile</b></td><td><b>Final Equity</b></td><td><b>Return</b></td><td><b>Max DD</b></td></tr>
            {pct_rows}
          </table>
        </section>
        """

    generated_at = datetime.now(timezone.utc).isoformat()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Backtest Report — {run.config.name}</title>
  <style>{_REPORT_CSS}</style>
</head>
<body>
  <h1>{run.config.name}</h1>
  <p class="subtitle">
    {', '.join(run.config.symbols)} · {run.config.primary_timeframe.value} ·
    {run.config.start_date} → {run.config.end_date} ·
    <span class="badge {status_class}">{run.status.value}</span>
  </p>

  <section>
    <h2>Performance Summary</h2>
    <table>{perf_html}</table>
  </section>

  {walk_forward_html}
  {monte_carlo_html}

  <section>
    <h2>Trades</h2>
    <p>{len(bundle.trades)} simulated trades. See /backtest/{run.id}/trades for full ledger.</p>
  </section>

  <p style="color:#999; font-size: 0.8rem;">Generated {generated_at} by backtesting_engine_service</p>
</body>
</html>"""


def equity_curve_chart_data(bundle: BacktestResultBundle) -> dict:
    return {
        "labels": [p.ts.isoformat() for p in bundle.equity_curve],
        "series": [
            {
                "name": "Equity",
                "data": [p.equity_inr for p in bundle.equity_curve],
            },
            {
                "name": "Benchmark",
                "data": [p.benchmark_equity_inr for p in bundle.equity_curve],
            },
        ],
        "drawdown_pct": [p.drawdown_pct for p in bundle.equity_curve],
    }


def trade_distribution_chart_data(trades: list[SimulatedTrade], bins: int = 20) -> dict:
    pnls = [t.realized_pnl_pct for t in trades if t.realized_pnl_pct is not None]
    if not pnls:
        return {"bin_edges": [], "counts": []}
    counts, edges = np.histogram(pnls, bins=bins)
    return {"bin_edges": edges.tolist(), "counts": counts.tolist()}


def monte_carlo_fan_chart_data(bundle: BacktestResultBundle) -> dict:
    if not bundle.monte_carlo:
        return {}
    return {
        "percentiles": [p.model_dump() for p in bundle.monte_carlo.percentiles],
        "original_total_return_pct": bundle.monte_carlo.original_metrics.total_return_pct,
        "probability_of_loss_pct": bundle.monte_carlo.probability_of_loss_pct,
        "probability_of_ruin_pct": bundle.monte_carlo.probability_of_ruin_pct,
    }
