"use client";

import { useState } from "react";
import { useTradeLedger } from "@/hooks/use-data";
import { ExecutionFeed } from "@/components/shared/ExecutionFeed";
import { formatInr, formatInrCompact, formatDateTime, pnlClass } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";

export function TradesContent() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useTradeLedger(page, 50);

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Live executions */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Live Execution Feed</span>
          <span className="live-dot" />
        </div>
        <div className="max-h-52 overflow-y-auto">
          <ExecutionFeed limit={20} />
        </div>
      </div>

      {/* Trade ledger */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">Trade Ledger</span>
          <span className="text-xs text-text-muted">
            {data?.total ?? 0} trades
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Symbol</th>
                <th>Side</th>
                <th className="text-right">Qty</th>
                <th className="text-right">Price</th>
                <th className="text-right">Value</th>
                <th className="text-right">Realised P&L</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="text-center py-8 text-text-muted">Loading…</td>
                </tr>
              ) : data?.items.map((t) => (
                <tr key={t.trade_id}>
                  <td className="text-2xs text-text-muted font-mono whitespace-nowrap">
                    {formatDateTime(t.executed_at)}
                  </td>
                  <td className="font-mono font-semibold text-text-primary">{t.symbol}</td>
                  <td>
                    <span className={cn(
                      "badge text-2xs",
                      t.action === "BUY" ? "badge-bull" : "badge-bear"
                    )}>
                      {t.action}
                    </span>
                  </td>
                  <td className="text-right font-mono">{t.quantity}</td>
                  <td className="text-right font-mono">{formatInr(t.price_inr)}</td>
                  <td className="text-right font-mono">{formatInrCompact(t.value_inr)}</td>
                  <td className={cn("text-right font-mono", t.realised_pnl_inr != null ? pnlClass(t.realised_pnl_inr) : "text-text-muted")}>
                    {t.realised_pnl_inr != null ? formatInrCompact(t.realised_pnl_inr) : "—"}
                  </td>
                </tr>
              ))}
              {!isLoading && data?.items.length === 0 && (
                <tr>
                  <td colSpan={7} className="text-center py-8 text-text-muted">No trades yet</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        {/* Pagination */}
        {data && data.total > 50 && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-border">
            <span className="text-xs text-text-muted">
              Page {page} of {Math.ceil(data.total / 50)}
            </span>
            <div className="flex gap-2">
              <button
                className="btn-secondary text-xs px-3 py-1.5"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                Prev
              </button>
              <button
                className="btn-secondary text-xs px-3 py-1.5"
                onClick={() => setPage((p) => p + 1)}
                disabled={page >= Math.ceil(data.total / 50)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
