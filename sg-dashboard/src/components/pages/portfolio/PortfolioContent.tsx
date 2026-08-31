"use client";

import { useState } from "react";
import {
  usePortfolioSnapshot,
  usePortfolioExposure,
  usePerformanceMetrics,
} from "@/hooks/use-data";
import {
  formatInr,
  formatInrCompact,
  formatPct,
  pnlClass,
  pnlBgClass,
} from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { PortfolioMiniChart } from "@/components/charts/PortfolioMiniChart";
import { AllocationChart } from "@/components/charts/AllocationChart";
import type { PerformanceWindow } from "@/types";

const WINDOWS: { label: string; value: PerformanceWindow }[] = [
  { label: "1D", value: "1d" },
  { label: "7D", value: "7d" },
  { label: "1M", value: "30d" },
  { label: "3M", value: "90d" },
  { label: "1Y", value: "252d" },
  { label: "All", value: "inception" },
];

export function PortfolioContent() {
  const [window, setWindow] = useState<PerformanceWindow>("30d");
  const { data: snapshot, isLoading } = usePortfolioSnapshot();
  const { data: exposure } = usePortfolioExposure();
  const { data: perf } = usePerformanceMetrics(window);

  if (isLoading) {
    return <div className="h-64 bg-surface rounded-lg animate-pulse" />;
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Header metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="card p-5">
          <div className="metric-label mb-1">Total Value</div>
          <div className="metric-value text-accent">{snapshot ? formatInrCompact(snapshot.total_value_inr) : "—"}</div>
          <div className={cn("text-xs mt-1 font-mono", pnlClass(snapshot?.total_pnl_inr ?? 0))}>
            {snapshot ? `${formatPct(snapshot.total_pnl_pct, 2, true)} unrealised` : ""}
          </div>
        </div>
        <div className="card p-5">
          <div className="metric-label mb-1">Day P&L</div>
          <div className={cn("metric-value", pnlClass(snapshot?.day_pnl_inr ?? 0))}>
            {snapshot ? formatInrCompact(snapshot.day_pnl_inr) : "—"}
          </div>
          <div className="text-xs mt-1 text-text-muted font-mono">
            {snapshot ? formatPct(snapshot.day_pnl_pct, 2, true) : ""}
          </div>
        </div>
        <div className="card p-5">
          <div className="metric-label mb-1">Invested</div>
          <div className="metric-value">{snapshot ? formatInrCompact(snapshot.invested_inr) : "—"}</div>
          <div className="text-xs mt-1 text-text-muted">
            Cash: {snapshot ? formatInrCompact(snapshot.cash_inr) : "—"}
          </div>
        </div>
        <div className="card p-5">
          <div className="metric-label mb-1">Leverage</div>
          <div className="metric-value">{exposure ? `${exposure.leverage.toFixed(2)}x` : "—"}</div>
          <div className="text-xs mt-1 text-text-muted">
            {exposure ? `${formatPct(exposure.cash_pct)} cash` : ""}
          </div>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-3 gap-5">
        <div className="col-span-2 card">
          <div className="card-header">
            <span className="card-title">Equity Curve</span>
            <div className="flex gap-1">
              {WINDOWS.map((w) => (
                <button
                  key={w.value}
                  onClick={() => setWindow(w.value)}
                  className={cn(
                    "text-xs px-2 py-1 rounded transition-colors",
                    window === w.value
                      ? "bg-accent/10 text-accent"
                      : "text-text-muted hover:text-text-secondary"
                  )}
                >
                  {w.label}
                </button>
              ))}
            </div>
          </div>
          <div className="p-4 h-52">
            <PortfolioMiniChart />
          </div>
        </div>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Allocation</span>
          </div>
          <div className="p-4 h-52">
            <AllocationChart positions={snapshot?.positions ?? []} />
          </div>
        </div>
      </div>

      {/* Performance metrics */}
      {perf && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Performance Metrics ({window})</span>
          </div>
          <div className="p-5 grid grid-cols-4 lg:grid-cols-8 gap-4">
            {[
              { label: "Total Return", value: formatPct(perf.total_return_pct, 2, true), positive: perf.total_return_pct > 0 },
              { label: "Ann. Return", value: formatPct(perf.annualised_return_pct, 2, true), positive: perf.annualised_return_pct > 0 },
              { label: "Sharpe", value: perf.sharpe_ratio.toFixed(2), positive: perf.sharpe_ratio > 1 },
              { label: "Sortino", value: perf.sortino_ratio.toFixed(2), positive: perf.sortino_ratio > 1 },
              { label: "Max DD", value: formatPct(perf.max_drawdown_pct), positive: false },
              { label: "Win Rate", value: formatPct(perf.win_rate_pct), positive: perf.win_rate_pct > 50 },
              { label: "Alpha", value: perf.alpha.toFixed(3), positive: perf.alpha > 0 },
              { label: "Beta", value: perf.beta.toFixed(2), positive: true },
            ].map((m) => (
              <div key={m.label} className="text-center">
                <div className="text-2xs text-text-muted uppercase tracking-wider mb-1">{m.label}</div>
                <div className={cn("text-sm font-mono font-semibold", m.positive ? "text-bull" : m.label === "Max DD" ? "text-bear" : "text-text-primary")}>
                  {m.value}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Positions table */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Open Positions</span>
          <span className="text-xs text-text-muted">{snapshot?.positions.length ?? 0} holdings</span>
        </div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Avg Cost</th>
                <th className="text-right">LTP</th>
                <th className="text-right">Market Value</th>
                <th className="text-right">Unrealised P&L</th>
                <th className="text-right">Day P&L</th>
                <th className="text-right">Weight</th>
              </tr>
            </thead>
            <tbody>
              {snapshot?.positions.map((p) => (
                <tr key={p.symbol}>
                  <td className="font-mono font-semibold text-text-primary">{p.symbol}</td>
                  <td className="text-right font-mono">{p.quantity}</td>
                  <td className="text-right font-mono">{formatInr(p.avg_cost_inr)}</td>
                  <td className="text-right font-mono">{formatInr(p.ltp)}</td>
                  <td className="text-right font-mono">{formatInrCompact(p.market_value_inr)}</td>
                  <td className={cn("text-right font-mono", pnlClass(p.unrealised_pnl_inr))}>
                    <div>{formatInrCompact(p.unrealised_pnl_inr)}</div>
                    <div className="text-2xs">{formatPct(p.unrealised_pnl_pct, 2, true)}</div>
                  </td>
                  <td className={cn("text-right font-mono", pnlClass(p.day_pnl_inr))}>
                    {formatInrCompact(p.day_pnl_inr)}
                  </td>
                  <td className="text-right font-mono text-text-muted">
                    {formatPct(p.weight_pct)}
                  </td>
                </tr>
              ))}
              {(!snapshot?.positions || snapshot.positions.length === 0) && (
                <tr>
                  <td colSpan={8} className="text-center text-text-muted py-8">No open positions</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
