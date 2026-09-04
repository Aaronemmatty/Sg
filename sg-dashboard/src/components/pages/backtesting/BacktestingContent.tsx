"use client";

import { useState } from "react";
import {
  useBacktestRuns,
  useBacktestMetrics,
  useEquityCurve,
  useBacktestTrades,
  useStrategies,
  useSymbols,
} from "@/hooks/use-data";
import { clientFetch } from "@/lib/api/client";
import {
  formatPct,
  formatInrCompact,
  formatDateTime,
  formatRelative,
  pnlClass,
} from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { FlaskConical, Play, Loader2, TrendingUp, TrendingDown } from "lucide-react";
import toast from "react-hot-toast";
import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, CartesianGrid
} from "recharts";
import { formatDateShort } from "@/lib/utils/format";
import type { BacktestRun, Interval } from "@/types";

const INTERVALS: Interval[] = ["1m", "5m", "15m", "30m", "1h", "1d"];

const STATUS_BADGE: Record<string, string> = {
  pending: "badge-neutral",
  running: "badge-warning",
  completed: "badge-bull",
  failed: "badge-bear",
};

function RunForm({ onSubmit }: { onSubmit: () => void }) {
  const { data: strategies } = useStrategies();
  const { data: symbols } = useSymbols();

  const [form, setForm] = useState({
    strategy_id: "",
    symbol: "",
    interval: "1d" as Interval,
    start_date: "2023-01-01",
    end_date: new Date().toISOString().slice(0, 10),
    use_ml_signals: false,
    walk_forward: false,
  });
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!form.strategy_id || !form.symbol) {
      toast.error("Strategy and symbol are required");
      return;
    }
    setSubmitting(true);
    try {
      await clientFetch("backtesting/runs", {
        method: "POST",
        body: JSON.stringify(form),
      });
      toast.success("Backtest submitted");
      onSubmit();
    } catch {
      toast.error("Failed to submit backtest");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <span className="card-title">New Backtest</span>
        <FlaskConical className="w-3.5 h-3.5 text-text-muted" />
      </div>
      <div className="p-5 grid grid-cols-3 gap-4">
        <div>
          <label className="block text-xs text-text-muted mb-1.5">Strategy</label>
          <select
            className="input"
            value={form.strategy_id}
            onChange={(e) => setForm({ ...form, strategy_id: e.target.value })}
          >
            <option value="">Select strategy…</option>
            {strategies?.map((s) => (
              <option key={s.strategy_id} value={s.strategy_id}>{s.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1.5">Symbol</label>
          <select
            className="input"
            value={form.symbol}
            onChange={(e) => setForm({ ...form, symbol: e.target.value })}
          >
            <option value="">Select symbol…</option>
            {symbols?.map((s) => (
              <option key={s.symbol} value={s.symbol}>{s.symbol} — {s.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1.5">Interval</label>
          <select
            className="input"
            value={form.interval}
            onChange={(e) => setForm({ ...form, interval: e.target.value as Interval })}
          >
            {INTERVALS.map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1.5">Start Date</label>
          <input
            type="date"
            className="input"
            value={form.start_date}
            onChange={(e) => setForm({ ...form, start_date: e.target.value })}
          />
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1.5">End Date</label>
          <input
            type="date"
            className="input"
            value={form.end_date}
            onChange={(e) => setForm({ ...form, end_date: e.target.value })}
          />
        </div>
        <div className="flex flex-col justify-end gap-2">
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={form.use_ml_signals}
              onChange={(e) => setForm({ ...form, use_ml_signals: e.target.checked })}
              className="w-3.5 h-3.5 accent-amber-500"
            />
            Overlay ML signals
          </label>
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={form.walk_forward}
              onChange={(e) => setForm({ ...form, walk_forward: e.target.checked })}
              className="w-3.5 h-3.5 accent-amber-500"
            />
            Walk-forward analysis
          </label>
        </div>
        <div className="col-span-3 flex justify-end">
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="btn-primary gap-2"
          >
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            Run Backtest
          </button>
        </div>
      </div>
    </div>
  );
}

function BacktestResultPanel({ run }: { run: BacktestRun }) {
  const { data: metrics } = useBacktestMetrics(run.backtest_id);
  const { data: curve } = useEquityCurve(run.backtest_id);
  const { data: trades } = useBacktestTrades(run.backtest_id);

  if (run.status !== "completed") {
    return (
      <div className="card p-8 text-center">
        <Loader2 className="w-6 h-6 animate-spin text-accent mx-auto mb-2" />
        <div className="text-sm text-text-secondary">{run.status === "running" ? `Running… ${run.progress_pct.toFixed(0)}%` : "Pending"}</div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Metrics grid */}
      {metrics && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Results — {run.strategy_name} / {run.symbol}</span>
          </div>
          <div className="p-5 grid grid-cols-4 lg:grid-cols-8 gap-4">
            {[
              { label: "Total Return", value: metrics.total_return_pct != null ? formatPct(metrics.total_return_pct, 2, true) : "—", pos: (metrics.total_return_pct ?? 0) > 0 },
              { label: "Ann. Return", value: metrics.annualised_return_pct != null ? formatPct(metrics.annualised_return_pct, 2, true) : "—", pos: (metrics.annualised_return_pct ?? 0) > 0 },
              { label: "Sharpe", value: metrics.sharpe_ratio != null ? metrics.sharpe_ratio.toFixed(2) : "—", pos: (metrics.sharpe_ratio ?? 0) > 1 },
              { label: "Sortino", value: metrics.sortino_ratio != null ? metrics.sortino_ratio.toFixed(2) : "—", pos: (metrics.sortino_ratio ?? 0) > 1 },
              { label: "Max DD", value: metrics.max_drawdown_pct != null ? formatPct(metrics.max_drawdown_pct) : "—", pos: false, bear: true },
              { label: "Win Rate", value: metrics.win_rate_pct != null ? formatPct(metrics.win_rate_pct) : "—", pos: (metrics.win_rate_pct ?? 0) > 50 },
              { label: "vs Benchmark", value: (metrics.total_return_pct != null && metrics.benchmark_return_pct != null) ? formatPct(metrics.total_return_pct - metrics.benchmark_return_pct, 2, true) : "—", pos: (metrics.total_return_pct ?? 0) > (metrics.benchmark_return_pct ?? 0) },
              { label: "Trades", value: metrics.total_trades != null ? String(metrics.total_trades) : "0", pos: true },
            ].map((m) => (
              <div key={m.label} className="text-center">
                <div className="text-2xs text-text-muted uppercase tracking-wider mb-1">{m.label}</div>
                <div className={cn(
                  "text-sm font-mono font-semibold",
                  m.bear ? "text-bear" : m.pos ? "text-bull" : "text-text-primary"
                )}>
                  {m.value}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Equity curve */}
      {curve && curve.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Equity Curve vs Benchmark</span>
          </div>
          <div className="p-4 h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={curve} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="strat" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10B981" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#10B981" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="bench" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6B7280" stopOpacity={0.15} />
                    <stop offset="95%" stopColor="#6B7280" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#1E2D45" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="timestamp" tickFormatter={formatDateShort} tick={{ fill: "#475569", fontSize: 10 }} tickLine={false} axisLine={false} interval="preserveStartEnd" />
                <YAxis tickFormatter={formatInrCompact} tick={{ fill: "#475569", fontSize: 10 }} tickLine={false} axisLine={false} width={55} />
                <Tooltip
                  contentStyle={{ background: "#1A2235", border: "1px solid #1E2D45", borderRadius: "6px", fontSize: "11px", color: "#F1F5F9" }}
                  labelFormatter={formatDateShort}
                  formatter={(v: number, name: string) => [formatInrCompact(v), name]}
                />
                <Legend wrapperStyle={{ fontSize: "11px", color: "#94A3B8" }} />
                <Area type="monotone" dataKey="equity_inr" name="Strategy" stroke="#10B981" strokeWidth={1.5} fill="url(#strat)" dot={false} />
                <Area type="monotone" dataKey="benchmark_inr" name="Benchmark" stroke="#6B7280" strokeWidth={1} fill="url(#bench)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Trades */}
      {trades && trades.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Trade Log</span>
            <span className="text-xs text-text-muted">{trades.length} trades</span>
          </div>
          <div className="overflow-x-auto max-h-64 overflow-y-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Entry</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th className="text-right">Entry Price</th>
                  <th className="text-right">Exit Price</th>
                  <th className="text-right">P&L</th>
                </tr>
              </thead>
              <tbody>
                {trades.slice(0, 100).map((t) => (
                  <tr key={t.trade_id}>
                    <td className="text-2xs text-text-muted font-mono">{formatDateTime(t.entered_at)}</td>
                    <td className="font-mono font-semibold">{t.symbol}</td>
                    <td>
                      <span className={cn("badge text-2xs", t.action === "BUY" ? "badge-bull" : "badge-bear")}>
                        {t.action}
                      </span>
                    </td>
                    <td className="text-right font-mono">{formatInrCompact(t.entry_price)}</td>
                    <td className="text-right font-mono text-text-muted">
                      {t.exit_price != null ? formatInrCompact(t.exit_price) : "—"}
                    </td>
                    <td className={cn("text-right font-mono", t.pnl_inr != null ? pnlClass(t.pnl_inr) : "text-text-muted")}>
                      {t.pnl_inr != null ? formatInrCompact(t.pnl_inr) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export function BacktestingContent() {
  const { data: runs, mutate } = useBacktestRuns();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selectedRun = runs?.find((r) => r.backtest_id === selectedId);

  return (
    <div className="space-y-5 animate-fade-in">
      <RunForm onSubmit={() => mutate()} />

      <div className="grid grid-cols-3 gap-5">
        {/* Run list */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Backtest Runs</span>
            <span className="text-xs text-text-muted">{runs?.length ?? 0}</span>
          </div>
          <div className="divide-y divide-border max-h-[600px] overflow-y-auto">
            {runs?.map((r) => (
              <div
                key={r.backtest_id}
                onClick={() => setSelectedId(r.backtest_id === selectedId ? null : r.backtest_id)}
                className={cn(
                  "px-4 py-3 cursor-pointer transition-colors",
                  selectedId === r.backtest_id
                    ? "bg-accent/5 border-l-2 border-accent"
                    : "hover:bg-surface-2/50"
                )}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-semibold text-text-primary">{r.strategy_name}</span>
                  <span className={cn("badge text-2xs", STATUS_BADGE[r.status] ?? "badge-neutral")}>
                    {r.status}
                  </span>
                </div>
                <div className="text-2xs text-text-muted font-mono">{r.symbol} · {r.interval}</div>
                <div className="text-2xs text-text-muted mt-0.5">{formatRelative(r.submitted_at)}</div>
                {r.status === "running" && (
                  <div className="mt-1.5 h-1 bg-surface-3 rounded-full overflow-hidden">
                    <div className="h-full bg-accent rounded-full" style={{ width: `${r.progress_pct}%` }} />
                  </div>
                )}
              </div>
            ))}
            {!runs?.length && (
              <div className="py-10 text-center text-sm text-text-muted">No backtests yet</div>
            )}
          </div>
        </div>

        {/* Results panel */}
        <div className="col-span-2">
          {selectedRun ? (
            <BacktestResultPanel run={selectedRun} />
          ) : (
            <div className="card p-12 text-center text-sm text-text-muted">
              Select a backtest run to view results
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
