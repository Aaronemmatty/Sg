"use client";

import { useRiskMetrics } from "@/hooks/use-data";
import { useStore } from "@/lib/stores/app.store";
import { formatInrCompact, formatPct } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { RiskEventFeed } from "@/components/shared/RiskEventFeed";
import { ShieldAlert, AlertTriangle } from "lucide-react";

function LimitBar({
  label,
  used,
  limit,
  invert = false,
}: {
  label: string;
  used: number;
  limit: number;
  invert?: boolean;
}) {
  const pct = Math.min((used / limit) * 100, 100);
  const danger = pct > 80;
  const warn = pct > 60;

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-xs text-text-secondary">{label}</span>
        <span className="text-xs font-mono text-text-primary">
          {formatInrCompact(used)} / {formatInrCompact(limit)}
        </span>
      </div>
      <div className="h-2 bg-surface-3 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            danger ? "bg-bear" : warn ? "bg-warning" : "bg-bull"
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between mt-1">
        <span className="text-2xs text-text-muted">{formatPct(pct)} used</span>
        <span className="text-2xs text-text-muted">{formatPct(100 - pct)} remaining</span>
      </div>
    </div>
  );
}

export function RiskContent() {
  const { data: risk, isLoading } = useRiskMetrics();
  const circuitBreakerActive = useStore((s) => s.circuitBreakerActive);

  if (isLoading) {
    return <div className="h-64 bg-surface rounded-lg animate-pulse" />;
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Circuit breaker banner */}
      {circuitBreakerActive && (
        <div className="flex items-center gap-4 p-5 bg-bear/10 border border-bear/40 rounded-lg">
          <ShieldAlert className="w-6 h-6 text-bear shrink-0" />
          <div>
            <div className="text-sm font-bold text-bear">Circuit Breaker Triggered</div>
            <div className="text-xs text-bear/80 mt-0.5">
              All order routing is suspended. Contact risk officer to reset.
            </div>
          </div>
        </div>
      )}

      {/* VaR / CVaR */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "VaR 95%", value: risk ? formatInrCompact(risk.var_95_inr) : "—", sub: "1-day 95% confidence" },
          { label: "VaR 99%", value: risk ? formatInrCompact(risk.var_99_inr) : "—", sub: "1-day 99% confidence" },
          { label: "CVaR 95%", value: risk ? formatInrCompact(risk.cvar_95_inr) : "—", sub: "Expected shortfall" },
          { label: "Current Drawdown", value: risk ? formatPct(risk.current_drawdown_pct) : "—", sub: `Limit: ${risk ? formatPct(risk.drawdown_limit_pct) : "—"}`, warn: risk ? risk.current_drawdown_pct > risk.drawdown_limit_pct * 0.8 : false },
        ].map((m) => (
          <div key={m.label} className={cn("card p-5", m.warn && "border-warning/30")}>
            <div className="metric-label mb-1">{m.label}</div>
            <div className={cn("metric-value", m.warn ? "text-warning" : "")}>{m.value}</div>
            <div className="text-2xs text-text-muted mt-1">{m.sub}</div>
          </div>
        ))}
      </div>

      {/* Limit utilization */}
      <div className="grid grid-cols-2 gap-5">
        <div className="card">
          <div className="card-header">
            <span className="card-title">Daily Loss Limit</span>
            <AlertTriangle className="w-3.5 h-3.5 text-text-muted" />
          </div>
          <div className="p-5 space-y-4">
            {risk && (
              <LimitBar
                label="Daily Loss Used"
                used={risk.daily_loss_used_inr}
                limit={risk.daily_loss_limit_inr}
              />
            )}
            {risk && (
              <div className="text-sm text-text-muted">
                Remaining: <span className="font-mono text-bull">{formatInrCompact(risk.daily_loss_remaining_inr)}</span>
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Position Limits</span>
          </div>
          <div className="p-5 space-y-4">
            {risk && (
              <>
                <div className="flex justify-between text-sm">
                  <span className="text-text-secondary">Max Position Size</span>
                  <span className="font-mono text-text-primary">{formatPct(risk.max_position_size_pct)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-text-secondary">Top-5 Concentration</span>
                  <span className={cn("font-mono", risk.concentration_top5_pct > 70 ? "text-warning" : "text-text-primary")}>
                    {formatPct(risk.concentration_top5_pct)}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-text-secondary">Drawdown Limit</span>
                  <span className="font-mono text-text-primary">{formatPct(risk.drawdown_limit_pct)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-text-secondary">Circuit Breaker</span>
                  <span className={cn("font-semibold", risk.circuit_breaker_active ? "text-bear" : "text-bull")}>
                    {risk.circuit_breaker_active ? "ACTIVE" : "OK"}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Risk event feed */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Risk Event Log</span>
          <span className="live-dot" />
        </div>
        <div className="max-h-80 overflow-y-auto">
          <RiskEventFeed limit={50} />
        </div>
      </div>
    </div>
  );
}
