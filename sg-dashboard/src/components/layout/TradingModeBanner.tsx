"use client";

import { useBrokerStatus } from "@/hooks/use-data";
import { cn } from "@/lib/utils/cn";
import { ShieldCheck, AlertOctagon, Radio, ShieldAlert } from "lucide-react";

export function TradingModeBanner() {
  const { data: brokerStatus, isLoading, error } = useBrokerStatus();

  // If loading and no previous data, render a subtle placeholder
  if (isLoading && !brokerStatus) {
    return (
      <div className="w-full bg-surface-2/60 border-b border-border px-4 py-1.5 flex items-center justify-between text-2xs text-text-muted">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-neutral animate-pulse" />
          <span>Checking broker trading mode...</span>
        </div>
      </div>
    );
  }

  const isLive = brokerStatus?.mode === "live";
  const isConnected = brokerStatus?.connected ?? false;
  const brokerName = brokerStatus?.broker ? brokerStatus.broker.toUpperCase() : (isLive ? "ZERODHA KITE" : "PAPER BROKER");

  if (isLive) {
    return (
      <div
        id="trading-mode-banner"
        className="w-full bg-bear/15 border-b-2 border-bear text-bear px-4 py-2 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 shadow-glow-bear transition-all duration-300 shrink-0"
      >
        <div className="flex items-center gap-3">
          <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-bear/20 border border-bear/40 text-bear shrink-0">
            <AlertOctagon className="w-4 h-4 animate-pulse" />
            <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-bear opacity-75" />
              <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-bear" />
            </span>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-black tracking-wider uppercase bg-bear/25 px-2 py-0.5 rounded border border-bear/50 text-bear">
                LIVE TRADING ACTIVE — REAL CAPITAL AT RISK
              </span>
              <span className="hidden md:inline-block text-2xs font-semibold text-bear/90">
                Broker: {brokerName}
              </span>
            </div>
            <p className="text-2xs text-bear/90 font-medium mt-0.5">
              All automated & manual orders execute live against real market exchange accounts.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 self-end sm:self-auto text-2xs font-mono">
          <span
            className={cn(
              "inline-flex items-center gap-1.5 px-2.5 py-1 rounded font-bold border",
              isConnected
                ? "bg-bear/20 border-bear/50 text-bear"
                : "bg-warning/20 border-warning/50 text-warning"
            )}
          >
            <span
              className={cn(
                "w-2 h-2 rounded-full",
                isConnected ? "bg-bear animate-ping" : "bg-warning"
              )}
            />
            {isConnected ? "KITE CONNECTED" : "KITE DISCONNECTED"}
          </span>
        </div>
      </div>
    );
  }

  // Paper / Simulated Mode Banner (High-contrast Bull / Emerald theme)
  return (
    <div
      id="trading-mode-banner"
      className="w-full bg-bull/[0.08] border-b border-bull/30 text-bull px-4 py-1.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-1.5 transition-all duration-300 shrink-0"
    >
      <div className="flex items-center gap-2.5">
        <div className="flex items-center justify-center w-6 h-6 rounded bg-bull/15 border border-bull/30 text-bull shrink-0">
          <ShieldCheck className="w-3.5 h-3.5" />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-2xs font-bold tracking-wider uppercase bg-bull/15 px-2 py-0.5 rounded border border-bull/30 text-bull">
            PAPER TRADING MODE
          </span>
          <span className="text-2xs text-text-secondary">
            Simulated order execution & positions. Zero real capital at risk.
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 self-end sm:self-auto text-2xs font-mono">
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-bull/10 border border-bull/20 text-bull font-medium">
          <span className="w-1.5 h-1.5 rounded-full bg-bull" />
          SIMULATION ACTIVE
        </span>
      </div>
    </div>
  );
}
