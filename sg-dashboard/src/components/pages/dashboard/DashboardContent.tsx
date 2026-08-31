"use client";

import { usePortfolioSnapshot, useRiskMetrics, useChampionModels, useRegimes, usePerformanceMetrics } from "@/hooks/use-data";
import { useStore } from "@/lib/stores/app.store";
import { formatInr, formatInrCompact, formatPct, pnlClass, pnlBgClass, directionClass } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { TrendingUp, TrendingDown, Activity, ShieldAlert, Brain, Cpu, AlertTriangle } from "lucide-react";
import { PortfolioMiniChart } from "@/components/charts/PortfolioMiniChart";
import { ExecutionFeed } from "@/components/shared/ExecutionFeed";
import { RiskEventFeed } from "@/components/shared/RiskEventFeed";

function StatCard({
  label,
  value,
  sub,
  subClass,
  icon: Icon,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  subClass?: string;
  icon?: React.ElementType;
  accent?: boolean;
}) {
  return (
    <div className={cn("card p-5", accent && "border-accent/20 shadow-glow-accent/20")}>
      <div className="flex items-start justify-between">
        <div>
          <div className="metric-label mb-2">{label}</div>
          <div className="metric-value">{value}</div>
          {sub && <div className={cn("text-xs mt-1 font-mono", subClass ?? "text-text-muted")}>{sub}</div>}
        </div>
        {Icon && (
          <div className={cn("p-2 rounded", accent ? "bg-accent/10" : "bg-surface-2")}>
            <Icon className={cn("w-4 h-4", accent ? "text-accent" : "text-text-muted")} />
          </div>
        )}
      </div>
    </div>
  );
}

export function DashboardContent() {
  const { data: snapshot, isLoading: snapLoading } = usePortfolioSnapshot();
  const { data: risk } = useRiskMetrics();
  const { data: champions } = useChampionModels();
  const { data: regimes } = useRegimes();
  const { data: perf } = usePerformanceMetrics("30d");
  const recentExecutions = useStore((s) => s.recentExecutions);
  const mlSignals = useStore((s) => s.mlSignals);
  const circuitBreakerActive = useStore((s) => s.circuitBreakerActive);

  if (snapLoading) {
    return (
      <div className="grid grid-cols-4 gap-4 animate-pulse">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="h-28 bg-surface rounded-lg" />
        ))}
      </div>
    );
  }

  const dayPnlPositive = (snapshot?.day_pnl_inr ?? 0) >= 0;
  const totalPnlPositive = (snapshot?.total_pnl_inr ?? 0) >= 0;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Circuit breaker alert */}
      {circuitBreakerActive && (
        <div className="flex items-center gap-3 p-4 bg-bear/10 border border-bear/30 rounded-lg text-bear">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <div>
            <div className="font-semibold text-sm">Circuit Breaker Active</div>
            <div className="text-xs text-bear/80">All order routing is paused. Check Risk panel for details.</div>
          </div>
        </div>
      )}

      {/* Top KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Portfolio Value"
          value={snapshot ? formatInrCompact(snapshot.total_value_inr) : "—"}
          sub={snapshot ? `${formatPct(snapshot.total_pnl_pct, 2, true)} all-time` : undefined}
          subClass={totalPnlPositive ? "text-bull" : "text-bear"}
          icon={TrendingUp}
          accent
        />
        <StatCard
          label="Day P&L"
          value={snapshot ? formatInrCompact(snapshot.day_pnl_inr) : "—"}
          sub={snapshot ? formatPct(snapshot.day_pnl_pct, 2, true) : undefined}
          subClass={dayPnlPositive ? "text-bull" : "text-bear"}
          icon={dayPnlPositive ? TrendingUp : TrendingDown}
        />
        <StatCard
          label="30d Sharpe"
          value={perf ? perf.sharpe_ratio.toFixed(2) : "—"}
          sub={perf ? `Sortino ${perf.sortino_ratio.toFixed(2)}` : undefined}
          icon={Activity}
        />
        <StatCard
          label="Daily VaR (95%)"
          value={risk ? formatInrCompact(risk.var_95_inr) : "—"}
          sub={risk ? `${formatPct(risk.daily_loss_used_inr / risk.daily_loss_limit_inr * 100)} daily limit used` : undefined}
          subClass={risk && risk.daily_loss_used_inr / risk.daily_loss_limit_inr > 0.8 ? "text-bear" : "text-text-muted"}
          icon={ShieldAlert}
        />
      </div>

      {/* Secondary KPIs */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Open Positions"
          value={String(snapshot?.positions.length ?? "—")}
          sub={snapshot ? `${formatInrCompact(snapshot.invested_inr)} deployed` : undefined}
        />
        <StatCard
          label="Cash Available"
          value={snapshot ? formatInrCompact(snapshot.cash_inr) : "—"}
          sub={snapshot ? `${formatPct((snapshot.cash_inr / snapshot.total_value_inr) * 100)} of portfolio` : undefined}
        />
        <StatCard
          label="Champion Models"
          value={String(champions?.length ?? "—")}
          sub="ML platform active"
          icon={Brain}
        />
        <StatCard
          label="Max Drawdown (30d)"
          value={perf ? formatPct(perf.max_drawdown_pct) : "—"}
          sub={perf ? `Win rate ${formatPct(perf.win_rate_pct)}` : undefined}
          icon={Activity}
        />
      </div>

      {/* Main content grid */}
      <div className="grid grid-cols-3 gap-5">
        {/* Equity mini chart */}
        <div className="col-span-2 card">
          <div className="card-header">
            <span className="card-title">Portfolio Equity</span>
            <span className="text-xs text-text-muted">30d</span>
          </div>
          <div className="p-4 h-48">
            <PortfolioMiniChart />
          </div>
        </div>

        {/* Regime overview */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Market Regime</span>
            <Cpu className="w-3.5 h-3.5 text-text-muted" />
          </div>
          <div className="p-4 space-y-3">
            {regimes?.slice(0, 5).map((r) => (
              <div key={r.symbol} className="flex items-center justify-between">
                <span className="text-xs font-mono text-text-secondary">{r.symbol}</span>
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "badge text-2xs",
                    r.regime === "bull" ? "badge-bull" :
                    r.regime === "bear" ? "badge-bear" : "badge-neutral"
                  )}>
                    {r.regime.toUpperCase()}
                  </span>
                  <span className="text-2xs text-text-muted font-mono">
                    {(r.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            ))}
            {(!regimes || regimes.length === 0) && (
              <div className="text-xs text-text-muted text-center py-4">No regime data</div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom row */}
      <div className="grid grid-cols-3 gap-5">
        {/* ML Signals */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">ML Signals</span>
            <Brain className="w-3.5 h-3.5 text-text-muted" />
          </div>
          <div className="divide-y divide-border">
            {Object.entries(mlSignals).slice(0, 6).map(([sym, sig]) => (
              <div key={sym} className="flex items-center justify-between px-4 py-2.5">
                <span className="text-xs font-mono text-text-secondary">{sym}</span>
                <div className="flex items-center gap-2">
                  <span className={cn("text-xs font-semibold", directionClass(sig.direction))}>
                    {sig.direction}
                  </span>
                  <span className="text-2xs text-text-muted font-mono">
                    {(sig.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            ))}
            {Object.keys(mlSignals).length === 0 && (
              <div className="text-xs text-text-muted text-center py-6">Awaiting signals…</div>
            )}
          </div>
        </div>

        {/* Recent executions */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Recent Executions</span>
            <span className="live-dot" />
          </div>
          <ExecutionFeed limit={6} compact />
        </div>

        {/* Risk events */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">Risk Events</span>
            <ShieldAlert className="w-3.5 h-3.5 text-text-muted" />
          </div>
          <RiskEventFeed limit={6} compact />
        </div>
      </div>
    </div>
  );
}
