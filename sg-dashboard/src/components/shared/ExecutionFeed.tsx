"use client";

import { useStore } from "@/lib/stores/app.store";
import { formatInr, formatTime, pnlClass } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import type { ExecutionEvent } from "@/types";

const STATE_COLORS: Record<string, string> = {
  FILLED: "text-bull",
  PARTIALLY_FILLED: "text-accent",
  REJECTED: "text-bear",
  CANCELLED: "text-bear",
  FAILED: "text-bear",
  ACKNOWLEDGED: "text-text-muted",
  ORDER_SUBMITTED: "text-text-muted",
  EXPIRED: "text-text-muted",
};

interface Props {
  limit?: number;
  compact?: boolean;
}

export function ExecutionFeed({ limit = 20, compact = false }: Props) {
  const executions = useStore((s) => s.recentExecutions).slice(0, limit);

  if (executions.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-xs text-text-muted">
        Waiting for executions…
      </div>
    );
  }

  return (
    <div className="divide-y divide-border overflow-y-auto">
      {executions.map((e) => (
        <ExecutionRow key={e.order_id} event={e} compact={compact} />
      ))}
    </div>
  );
}

function ExecutionRow({ event: e, compact }: { event: ExecutionEvent; compact: boolean }) {
  return (
    <div className={cn("flex items-start gap-2 px-4", compact ? "py-2" : "py-3")}>
      {/* Action badge */}
      <span className={cn(
        "text-2xs font-bold px-1.5 py-0.5 rounded shrink-0 mt-0.5",
        e.action === "BUY" ? "bg-bull/10 text-bull" : "bg-bear/10 text-bear"
      )}>
        {e.action}
      </span>

      {/* Details */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-text-primary font-mono">{e.symbol}</span>
          <span className={cn("text-2xs font-medium", STATE_COLORS[e.state] ?? "text-text-muted")}>
            {e.state.replace("_", " ")}
          </span>
        </div>
        {!compact && (
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-2xs text-text-muted">
              {e.filled_quantity}/{e.quantity} @ {formatInr(e.avg_fill_price_inr)}
            </span>
            {e.slippage_bps > 0 && (
              <span className="text-2xs text-text-muted">
                slip: {e.slippage_bps.toFixed(1)}bps
              </span>
            )}
          </div>
        )}
        <div className="text-2xs text-text-muted mt-0.5">{formatTime(e.emitted_at)}</div>
      </div>
    </div>
  );
}
