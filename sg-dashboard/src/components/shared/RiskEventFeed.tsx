"use client";

import { useStore } from "@/lib/stores/app.store";
import { formatRelative } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { AlertTriangle, Info, AlertCircle } from "lucide-react";
import type { RiskEvent } from "@/types";

const SEVERITY_CONFIG = {
  info: { icon: Info, class: "text-text-muted" },
  warning: { icon: AlertTriangle, class: "text-warning" },
  critical: { icon: AlertCircle, class: "text-bear" },
};

interface Props {
  limit?: number;
  compact?: boolean;
}

export function RiskEventFeed({ limit = 20, compact = false }: Props) {
  const events = useStore((s) => s.recentEvents).slice(0, limit);

  if (events.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-xs text-text-muted">
        No risk events
      </div>
    );
  }

  return (
    <div className="divide-y divide-border overflow-y-auto">
      {events.map((e) => (
        <RiskEventRow key={e.event_id} event={e} compact={compact} />
      ))}
    </div>
  );
}

function RiskEventRow({ event: e, compact }: { event: RiskEvent; compact: boolean }) {
  const cfg = SEVERITY_CONFIG[e.severity];
  const Icon = cfg.icon;

  return (
    <div className={cn("flex items-start gap-2.5 px-4", compact ? "py-2" : "py-3")}>
      <Icon className={cn("w-3.5 h-3.5 shrink-0 mt-0.5", cfg.class)} />
      <div className="flex-1 min-w-0">
        <div className="text-xs text-text-primary line-clamp-2">{e.message}</div>
        <div className="flex items-center gap-2 mt-1">
          {e.symbol && (
            <span className="text-2xs font-mono text-text-muted">{e.symbol}</span>
          )}
          <span className="text-2xs text-text-muted">{formatRelative(e.timestamp)}</span>
        </div>
      </div>
    </div>
  );
}
