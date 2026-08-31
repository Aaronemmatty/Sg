"use client";

import { Bell, Search, RefreshCw } from "lucide-react";
import { useStore } from "@/lib/stores/app.store";
import { formatInr, pnlClass } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { useState } from "react";

const WATCHLIST = ["NIFTY50", "RELIANCE", "TCS", "HDFC", "INFY", "ICICIBANK"];

export function TopBar({ title }: { title: string }) {
  const tickers = useStore((s) => s.tickers);
  const recentEvents = useStore((s) => s.recentEvents);
  const criticalEvents = recentEvents.filter((e) => e.severity === "critical");
  const [refreshing, setRefreshing] = useState(false);

  function handleRefresh() {
    setRefreshing(true);
    setTimeout(() => setRefreshing(false), 800);
    window.location.reload();
  }

  return (
    <header className="h-14 bg-surface border-b border-border flex items-center px-5 gap-4 shrink-0">
      {/* Page title */}
      <h1 className="text-sm font-semibold text-text-primary whitespace-nowrap">{title}</h1>

      {/* Market ticker tape */}
      <div className="flex-1 overflow-hidden">
        <div className="flex gap-5 overflow-x-auto scrollbar-none">
          {WATCHLIST.map((sym) => {
            const t = tickers[sym];
            if (!t) return (
              <div key={sym} className="flex items-center gap-1.5 shrink-0">
                <span className="text-xs text-text-muted font-mono">{sym}</span>
                <span className="text-xs text-text-muted">—</span>
              </div>
            );
            return (
              <div key={sym} className="flex items-center gap-1.5 shrink-0">
                <span className="text-2xs text-text-muted font-medium">{sym}</span>
                <span className="text-xs text-text-primary font-mono tabular-nums">
                  {formatInr(t.ltp)}
                </span>
                <span className={cn("text-2xs font-mono tabular-nums", pnlClass(t.change_pct))}>
                  {t.change_pct > 0 ? "+" : ""}{t.change_pct.toFixed(2)}%
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={handleRefresh}
          className="btn-ghost p-2 rounded"
          title="Refresh"
        >
          <RefreshCw className={cn("w-4 h-4", refreshing && "animate-spin")} />
        </button>

        <button className="btn-ghost p-2 rounded relative" title="Alerts">
          <Bell className="w-4 h-4" />
          {criticalEvents.length > 0 && (
            <span className="absolute top-1 right-1 w-2 h-2 bg-bear rounded-full" />
          )}
        </button>
      </div>
    </header>
  );
}
