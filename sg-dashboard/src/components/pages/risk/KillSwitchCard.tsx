"use client";

import { useKillSwitchStatus } from "@/hooks/use-data";
import { cn } from "@/lib/utils/cn";
import { ShieldCheck, ShieldAlert, AlertOctagon, Radio, Clock, User } from "lucide-react";
import type { KillSwitchState } from "@/types";

function formatStateLabel(state: KillSwitchState): string {
  switch (state) {
    case "NORMAL":
      return "NORMAL — ALL TRADING ACTIVE";
    case "HALTED_MANUAL":
      return "HALTED (MANUAL OVERRIDE)";
    case "HALTED_AUTO_DRAWDOWN":
      return "HALTED (DRAWDOWN BREACH)";
    case "HALTED_AUTO_DAILY_LOSS":
      return "HALTED (DAILY LOSS LIMIT)";
    case "HALTED_AUTO_CIRCUIT_BREAKER":
      return "HALTED (CIRCUIT BREAKER)";
    case "EMERGENCY_STOP":
      return "EMERGENCY STOP (CRITICAL)";
    default:
      return state;
  }
}

export function KillSwitchCard() {
  const { data: killSwitch, isLoading, error } = useKillSwitchStatus();

  if (isLoading) {
    return (
      <div className="card p-5 animate-pulse">
        <div className="h-6 w-48 bg-surface-3 rounded mb-2" />
        <div className="h-4 w-96 bg-surface-2 rounded" />
      </div>
    );
  }

  const state = killSwitch?.state || "NORMAL";
  const isHalted = killSwitch?.is_halted || state !== "NORMAL";
  const reason = killSwitch?.reason;
  const isEmergency = state === "EMERGENCY_STOP";

  if (!isHalted) {
    return (
      <div className="card p-5 border-bull/30 bg-bull/[0.03] transition-all duration-300">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3.5">
            <div className="relative flex items-center justify-center w-10 h-10 rounded-lg bg-bull/10 border border-bull/20 text-bull">
              <ShieldCheck className="w-5 h-5" />
              <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-bull opacity-75" />
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-bull" />
              </span>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold tracking-wider text-bull uppercase">
                  Kill Switch Status
                </span>
                <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-2xs font-semibold bg-bull/15 text-bull border border-bull/30">
                  <span className="w-1.5 h-1.5 rounded-full bg-bull" />
                  NORMAL
                </span>
              </div>
              <p className="text-xs text-text-secondary mt-0.5">
                Global trading safeguard is operational. All automated order flow and pre-trade checks are running.
              </p>
            </div>
          </div>

          <div className="hidden sm:flex items-center gap-2 text-2xs text-text-muted">
            <Radio className="w-3.5 h-3.5 text-bull animate-pulse" />
            <span>Live Polling (5s)</span>
          </div>
        </div>
      </div>
    );
  }

  // NOT NORMAL — High visibility Halt state
  return (
    <div
      className={cn(
        "card p-6 border-2 transition-all duration-300 shadow-xl",
        isEmergency
          ? "border-bear bg-bear/15 shadow-bear/20"
          : "border-bear/80 bg-bear/10 shadow-bear/10"
      )}
    >
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div className="flex items-start gap-4">
          <div
            className={cn(
              "flex items-center justify-center w-12 h-12 rounded-xl text-bear shrink-0 border",
              isEmergency
                ? "bg-bear/25 border-bear animate-bounce"
                : "bg-bear/20 border-bear/40"
            )}
          >
            {isEmergency ? (
              <AlertOctagon className="w-7 h-7" />
            ) : (
              <ShieldAlert className="w-7 h-7" />
            )}
          </div>

          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="text-xs font-bold tracking-wider text-bear uppercase">
                GLOBAL TRADING HALT ACTIVE
              </span>
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-bold bg-bear text-white shadow-sm">
                <span className="w-2 h-2 rounded-full bg-white animate-ping" />
                {formatStateLabel(state)}
              </span>
            </div>

            <p className="text-sm font-medium text-text-primary">
              All order routing and intent execution are strictly suspended across all strategies.
            </p>

            {reason && (
              <div className="mt-2.5 p-3 rounded-lg bg-surface/80 border border-bear/30 text-xs">
                <span className="text-text-muted font-semibold">Halt Reason: </span>
                <span className="text-text-primary font-mono">{reason}</span>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-4 text-2xs text-text-muted pt-1">
              {killSwitch?.actor && (
                <span className="flex items-center gap-1">
                  <User className="w-3 h-3 text-text-secondary" />
                  <span>Triggered by: <strong className="text-text-secondary">{killSwitch.actor}</strong></span>
                </span>
              )}
              {killSwitch?.updated_at && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3 text-text-secondary" />
                  <span>At: {new Date(killSwitch.updated_at).toLocaleTimeString()}</span>
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 self-end sm:self-auto text-2xs text-bear font-mono bg-bear/20 px-2.5 py-1 rounded border border-bear/30">
          <Radio className="w-3.5 h-3.5 animate-pulse" />
          <span>REAL-TIME HALT</span>
        </div>
      </div>
    </div>
  );
}
