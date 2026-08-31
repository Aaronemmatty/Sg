"use client";

import { useState } from "react";
import { useStrategies, useRegimes } from "@/hooks/use-data";
import { useStore } from "@/lib/stores/app.store";
import { formatRelative, directionClass } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { Cpu, Play, Pause, Activity } from "lucide-react";
import { clientFetch } from "@/lib/api/client";
import toast from "react-hot-toast";
import type { Strategy } from "@/types";

const STATUS_BADGE: Record<string, string> = {
  active: "badge-bull",
  paused: "badge-warning",
  stopped: "badge-neutral",
  error: "badge-bear",
};

export function StrategiesContent() {
  const { data: strategies, isLoading, mutate } = useStrategies();
  const { data: regimes } = useRegimes();
  const mlSignals = useStore((s) => s.mlSignals);
  const [selected, setSelected] = useState<string | null>(null);

  async function toggleStrategy(s: Strategy) {
    const action = s.status === "active" ? "pause" : "resume";
    try {
      await clientFetch(`strategies/${s.strategy_id}/${action}`, { method: "POST" });
      toast.success(`Strategy ${action}d`);
      mutate();
    } catch {
      toast.error(`Failed to ${action} strategy`);
    }
  }

  const selectedStrategy = strategies?.find((s) => s.strategy_id === selected);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Summary stats */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Total", value: strategies?.length ?? 0 },
          { label: "Active", value: strategies?.filter((s) => s.status === "active").length ?? 0 },
          { label: "Paused", value: strategies?.filter((s) => s.status === "paused").length ?? 0 },
          { label: "Error", value: strategies?.filter((s) => s.status === "error").length ?? 0 },
        ].map((stat) => (
          <div key={stat.label} className="card p-4">
            <div className="metric-label mb-1">{stat.label} Strategies</div>
            <div className="metric-value text-xl">{stat.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* Strategy list */}
        <div className="col-span-2 card">
          <div className="card-header">
            <span className="card-title">Strategy Registry</span>
            <Cpu className="w-3.5 h-3.5 text-text-muted" />
          </div>
          {isLoading ? (
            <div className="p-8 text-center text-text-muted text-sm">Loading…</div>
          ) : (
            <div className="divide-y divide-border">
              {strategies?.map((s) => (
                <div
                  key={s.strategy_id}
                  className={cn(
                    "flex items-center gap-4 px-5 py-4 cursor-pointer transition-colors",
                    selected === s.strategy_id
                      ? "bg-accent/5 border-l-2 border-accent"
                      : "hover:bg-surface-2/50"
                  )}
                  onClick={() => setSelected(s.strategy_id === selected ? null : s.strategy_id)}
                >
                  <div className={cn(
                    "w-2 h-2 rounded-full shrink-0",
                    s.status === "active" ? "bg-bull animate-pulse-slow" :
                    s.status === "error" ? "bg-bear" : "bg-neutral"
                  )} />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-text-primary">{s.name}</div>
                    <div className="text-xs text-text-muted mt-0.5">
                      {s.type} · {s.symbols.slice(0, 3).join(", ")}
                      {s.symbols.length > 3 && ` +${s.symbols.length - 3}`}
                    </div>
                  </div>
                  <span className={cn("badge text-2xs", STATUS_BADGE[s.status] ?? "badge-neutral")}>
                    {s.status}
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); toggleStrategy(s); }}
                    className={cn(
                      "p-1.5 rounded transition-colors",
                      s.status === "active"
                        ? "text-bull hover:bg-bull/10"
                        : "text-text-muted hover:bg-surface-3"
                    )}
                  >
                    {s.status === "active" ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                  </button>
                </div>
              ))}
              {strategies?.length === 0 && (
                <div className="py-12 text-center text-sm text-text-muted">No strategies registered</div>
              )}
            </div>
          )}
        </div>

        {/* Side panel — ML signals + regime per strategy */}
        <div className="space-y-4">
          {selectedStrategy ? (
            <div className="card">
              <div className="card-header">
                <span className="card-title">{selectedStrategy.name}</span>
              </div>
              <div className="p-4 space-y-4">
                <div>
                  <div className="text-2xs text-text-muted uppercase mb-2">Parameters</div>
                  <pre className="text-2xs text-text-secondary font-mono bg-surface-2 rounded p-3 overflow-x-auto">
                    {JSON.stringify(selectedStrategy.parameters, null, 2)}
                  </pre>
                </div>
                <div>
                  <div className="text-2xs text-text-muted uppercase mb-2">Symbol Signals</div>
                  <div className="space-y-1">
                    {selectedStrategy.symbols.map((sym) => {
                      const sig = mlSignals[sym];
                      const regime = regimes?.find((r) => r.symbol === sym);
                      return (
                        <div key={sym} className="flex items-center justify-between bg-surface-2 rounded px-3 py-2">
                          <span className="text-xs font-mono">{sym}</span>
                          <div className="flex items-center gap-2">
                            {sig && (
                              <span className={cn("text-2xs font-semibold", directionClass(sig.direction))}>
                                {sig.direction}
                              </span>
                            )}
                            {regime && (
                              <span className="badge-neutral text-2xs">
                                {regime.regime}
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="card p-8 text-center text-sm text-text-muted">
              Select a strategy to inspect
            </div>
          )}

          {/* ML signal overlay */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">Active ML Signals</span>
              <Activity className="w-3.5 h-3.5 text-text-muted" />
            </div>
            <div className="divide-y divide-border">
              {Object.entries(mlSignals).map(([sym, sig]) => (
                <div key={sym} className="flex items-center justify-between px-4 py-2.5">
                  <span className="text-xs font-mono text-text-secondary">{sym}</span>
                  <div className="flex items-center gap-2">
                    <span className={cn("text-xs font-semibold", directionClass(sig.direction))}>
                      {sig.direction}
                    </span>
                    <span className="text-2xs text-text-muted">
                      {(sig.confidence * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
              ))}
              {Object.keys(mlSignals).length === 0 && (
                <div className="py-6 text-center text-xs text-text-muted">No signals active</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
