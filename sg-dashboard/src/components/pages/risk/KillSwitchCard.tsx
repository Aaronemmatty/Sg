"use client";

import { useState } from "react";
import { useKillSwitchStatus, useCurrentUser } from "@/hooks/use-data";
import { clientFetch, ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils/cn";
import {
  ShieldCheck,
  ShieldAlert,
  AlertOctagon,
  Radio,
  Clock,
  User as UserIcon,
  PowerOff,
  Play,
  RotateCcw,
  AlertTriangle,
  Loader2,
  X,
  Lock,
} from "lucide-react";
import toast from "react-hot-toast";
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

type ActionType = "activate" | "deactivate" | "reset" | "emergency-stop";

interface ConfirmDialogProps {
  action: ActionType;
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (reason?: string) => Promise<void>;
  loading: boolean;
  canReset: boolean;
}

function KillSwitchModal({
  action,
  isOpen,
  onClose,
  onConfirm,
  loading,
  canReset,
}: ConfirmDialogProps) {
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState(false);

  if (!isOpen) return null;

  const requiresReason = action === "activate" || action === "emergency-stop";

  const handleConfirm = async () => {
    if (requiresReason && !reason.trim()) {
      setReasonError(true);
      return;
    }
    await onConfirm(reason.trim() || undefined);
    setReason("");
    setReasonError(false);
  };

  const getTitle = () => {
    switch (action) {
      case "activate":
        return "Confirm Manual Kill Switch Activation";
      case "deactivate":
        return "Confirm Deactivation & Resume Trading";
      case "reset":
        return "Confirm Safety Halt Reset";
      case "emergency-stop":
        return "EMERGENCY PLATFORM SHUTDOWN";
    }
  };

  const getDescription = () => {
    switch (action) {
      case "activate":
        return "This will halt ALL trading immediately across all strategies. No new orders will be submitted and active intent evaluation will pause.";
      case "deactivate":
        return "This will deactivate the manual halt and resume normal automated trading and order evaluation across all active strategies.";
      case "reset":
        return "This will clear an automatic safety halt — only do this after understanding why it triggered and confirming all risk conditions are resolved.";
      case "emergency-stop":
        return "CRITICAL ACTION: This immediately suspends all trading operations and locks the system in an emergency halt. Requires elevated Risk Officer authorization to reset.";
    }
  };

  const isEmergency = action === "emergency-stop";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
      <div
        className={cn(
          "card w-full max-w-lg p-6 bg-surface-1 border-2 shadow-2xl space-y-5 animate-scale-in",
          isEmergency
            ? "border-bear bg-bear/[0.04]"
            : action === "reset"
            ? "border-accent/40"
            : action === "deactivate"
            ? "border-bull/40"
            : "border-warning/40"
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "w-10 h-10 rounded-lg flex items-center justify-center shrink-0 border",
                isEmergency
                  ? "bg-bear/20 border-bear text-bear"
                  : action === "reset"
                  ? "bg-accent/20 border-accent text-accent"
                  : action === "deactivate"
                  ? "bg-bull/20 border-bull text-bull"
                  : "bg-warning/20 border-warning text-warning"
              )}
            >
              {isEmergency ? (
                <AlertOctagon className="w-5 h-5 animate-pulse" />
              ) : action === "reset" ? (
                <RotateCcw className="w-5 h-5" />
              ) : action === "deactivate" ? (
                <Play className="w-5 h-5" />
              ) : (
                <PowerOff className="w-5 h-5" />
              )}
            </div>
            <div>
              <h3 className="text-base font-bold text-text-primary tracking-tight">
                {getTitle()}
              </h3>
              <span className="text-2xs font-semibold uppercase tracking-wider text-text-muted">
                Safety-Critical Action Confirmation
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="p-1.5 rounded-lg text-text-muted hover:text-text-primary hover:bg-surface-2 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-3.5 rounded-lg bg-surface-2/60 border border-surface-3 text-xs leading-relaxed text-text-secondary">
          {getDescription()}
        </div>

        {action === "reset" && !canReset && (
          <div className="p-3 rounded-lg bg-bear/10 border border-bear/30 flex items-center gap-2.5 text-xs text-bear">
            <Lock className="w-4 h-4 shrink-0" />
            <span>
              <strong>Role Restriction:</strong> Resetting automatic halts requires the{" "}
              <code className="font-mono bg-bear/20 px-1 py-0.5 rounded">risk_officer</code> role.
            </span>
          </div>
        )}

        {requiresReason && (
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-text-secondary">
              Audit Reason <span className="text-bear">*</span>
              <span className="font-normal text-text-muted ml-1.5">
                (Recorded in immutable compliance log)
              </span>
            </label>
            <textarea
              value={reason}
              onChange={(e) => {
                setReason(e.target.value);
                if (e.target.value.trim()) setReasonError(false);
              }}
              placeholder={
                isEmergency
                  ? "e.g., Extreme volatility event / feed desync / broker connectivity issue"
                  : "e.g., Scheduled market holiday / operator precaution"
              }
              rows={3}
              className={cn(
                "w-full px-3 py-2 text-xs bg-surface-2 border rounded-lg text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 transition-all resize-none",
                reasonError
                  ? "border-bear focus:ring-bear"
                  : "border-surface-3 focus:ring-accent focus:border-accent"
              )}
            />
            {reasonError && (
              <p className="text-2xs font-medium text-bear">
                A valid reason is mandatory to record this safety action.
              </p>
            )}
          </div>
        )}

        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={loading}
            className="px-4 py-2 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-2 hover:bg-surface-3 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={loading}
            className={cn(
              "flex items-center gap-2 px-5 py-2 text-xs font-bold rounded-lg transition-all shadow-md active:scale-95 disabled:opacity-50",
              isEmergency
                ? "bg-bear hover:bg-bear/90 text-white shadow-bear/30"
                : action === "reset"
                ? "bg-accent hover:bg-accent/90 text-white shadow-accent/30"
                : action === "deactivate"
                ? "bg-bull hover:bg-bull/90 text-white shadow-bull/30"
                : "bg-warning hover:bg-warning/90 text-black shadow-warning/30"
            )}
          >
            {loading ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Executing...</span>
              </>
            ) : (
              <span>
                {isEmergency
                  ? "Confirm Emergency Stop"
                  : action === "reset"
                  ? "Confirm Reset"
                  : action === "deactivate"
                  ? "Resume Trading"
                  : "Activate Kill Switch"}
              </span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

export function KillSwitchCard() {
  const { data: killSwitch, isLoading, mutate } = useKillSwitchStatus();
  const { data: userData } = useCurrentUser();

  const [activeModal, setActiveModal] = useState<ActionType | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
  const isAutomatic =
    state === "HALTED_AUTO_DRAWDOWN" ||
    state === "HALTED_AUTO_DAILY_LOSS" ||
    state === "HALTED_AUTO_CIRCUIT_BREAKER" ||
    state === "EMERGENCY_STOP";

  const userRoles = userData?.user?.roles || [];
  const canReset = userRoles.includes("risk_officer") || userRoles.includes("admin");

  const handleAction = async (reasonText?: string) => {
    if (!activeModal) return;

    setSubmitting(true);
    try {
      if (activeModal === "activate") {
        await clientFetch("risk/kill-switch/activate", {
          method: "POST",
          body: JSON.stringify({ reason: reasonText || "Manual activation" }),
        });
        toast.success("Kill Switch activated: Trading halted manually");
      } else if (activeModal === "deactivate") {
        await clientFetch("risk/kill-switch/deactivate", {
          method: "POST",
        });
        toast.success("Kill Switch deactivated: Trading resumed");
      } else if (activeModal === "reset") {
        await clientFetch("risk/kill-switch/reset", {
          method: "POST",
        });
        toast.success("Safety halt reset: Trading state returned to NORMAL");
      } else if (activeModal === "emergency-stop") {
        await clientFetch("risk/emergency-stop", {
          method: "POST",
          body: JSON.stringify({ reason: reasonText || "Emergency stop triggered" }),
        });
        toast.error("EMERGENCY STOP TRIGGERED: Platform operations halted");
      }

      // Instant SWR cache invalidation
      await mutate();
      setActiveModal(null);
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (err.status === 403) {
          toast.error("Unauthorized: Requires risk_officer role to reset an automatic halt.");
        } else if (err.status === 409) {
          toast.error("Cannot resume: Automatic halts require an elevated Reset, not Deactivate.");
        } else {
          toast.error(err.message || "Failed to execute kill switch action");
        }
      } else {
        toast.error(err.message || "Network error occurred");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div
        className={cn(
          "card p-5 sm:p-6 transition-all duration-300 shadow-lg",
          !isHalted
            ? "border-bull/30 bg-bull/[0.03]"
            : isEmergency
            ? "border-bear bg-bear/15 shadow-bear/20 border-2"
            : "border-bear/80 bg-bear/10 shadow-bear/10 border-2"
        )}
      >
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-5">
          {/* Status & Info Left Side */}
          <div className="flex items-start gap-4">
            <div
              className={cn(
                "flex items-center justify-center w-12 h-12 rounded-xl shrink-0 border transition-transform",
                !isHalted
                  ? "bg-bull/10 border-bull/20 text-bull"
                  : isEmergency
                  ? "bg-bear/25 border-bear text-bear animate-bounce"
                  : "bg-bear/20 border-bear/40 text-bear"
              )}
            >
              {!isHalted ? (
                <ShieldCheck className="w-6 h-6" />
              ) : isEmergency ? (
                <AlertOctagon className="w-7 h-7" />
              ) : (
                <ShieldAlert className="w-7 h-7" />
              )}
            </div>

            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2.5">
                <span
                  className={cn(
                    "text-xs font-bold tracking-wider uppercase",
                    !isHalted ? "text-bull" : "text-bear"
                  )}
                >
                  {!isHalted ? "Kill Switch Status" : "GLOBAL TRADING HALT ACTIVE"}
                </span>
                <span
                  className={cn(
                    "inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded text-xs font-bold shadow-sm",
                    !isHalted
                      ? "bg-bull/15 text-bull border border-bull/30"
                      : "bg-bear text-white"
                  )}
                >
                  <span
                    className={cn(
                      "w-2 h-2 rounded-full",
                      !isHalted ? "bg-bull" : "bg-white animate-ping"
                    )}
                  />
                  {formatStateLabel(state)}
                </span>
              </div>

              <p className="text-xs sm:text-sm text-text-secondary font-medium">
                {!isHalted
                  ? "Global trading safeguard is operational. All automated order flow and pre-trade checks are running."
                  : "All order routing and intent execution are strictly suspended across all strategies."}
              </p>

              {reason && (
                <div className="mt-2.5 p-3 rounded-lg bg-surface/90 border border-bear/30 text-xs">
                  <span className="text-text-muted font-semibold">Halt Reason: </span>
                  <span className="text-text-primary font-mono">{reason}</span>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-4 text-2xs text-text-muted pt-1">
                {killSwitch?.actor && (
                  <span className="flex items-center gap-1">
                    <UserIcon className="w-3 h-3 text-text-secondary" />
                    <span>
                      Triggered by: <strong className="text-text-secondary">{killSwitch.actor}</strong>
                    </span>
                  </span>
                )}
                {killSwitch?.updated_at && (
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3 text-text-secondary" />
                    <span>At: {new Date(killSwitch.updated_at).toLocaleTimeString()}</span>
                  </span>
                )}
                <div className="flex items-center gap-1.5 font-mono">
                  <Radio
                    className={cn(
                      "w-3.5 h-3.5 animate-pulse",
                      !isHalted ? "text-bull" : "text-bear"
                    )}
                  />
                  <span>Live Polling (5s)</span>
                </div>
              </div>
            </div>
          </div>

          {/* Action Buttons Right Side */}
          <div className="flex flex-wrap sm:flex-nowrap items-center gap-2.5 lg:self-center shrink-0 border-t lg:border-t-0 pt-4 lg:pt-0 border-surface-2">
            {!isHalted ? (
              <>
                {/* Activate Manual Button */}
                <button
                  type="button"
                  onClick={() => setActiveModal("activate")}
                  className="flex-1 sm:flex-initial flex items-center justify-center gap-2 px-3.5 py-2 text-xs font-bold rounded-lg bg-warning/15 hover:bg-warning/25 text-warning border border-warning/30 hover:border-warning/50 transition-all shadow-sm active:scale-95"
                >
                  <PowerOff className="w-3.5 h-3.5" />
                  <span>Activate Kill Switch</span>
                </button>

                {/* Emergency Stop Button - Severe High-Contrast Break Glass */}
                <button
                  type="button"
                  onClick={() => setActiveModal("emergency-stop")}
                  className="flex-1 sm:flex-initial flex items-center justify-center gap-2 px-4 py-2 text-xs font-extrabold rounded-lg bg-bear hover:bg-bear/90 text-white border-2 border-red-700 shadow-md shadow-bear/30 hover:shadow-bear/50 transition-all active:scale-95 ring-2 ring-bear/20"
                >
                  <AlertOctagon className="w-4 h-4 animate-pulse" />
                  <span>EMERGENCY STOP</span>
                </button>
              </>
            ) : state === "HALTED_MANUAL" ? (
              <>
                {/* Deactivate Manual Resume */}
                <button
                  type="button"
                  onClick={() => setActiveModal("deactivate")}
                  className="flex-1 sm:flex-initial flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold rounded-lg bg-bull hover:bg-bull/90 text-white shadow-md shadow-bull/25 hover:shadow-bull/40 transition-all active:scale-95"
                >
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Resume Trading (Deactivate)</span>
                </button>

                {/* Escalate to Emergency Stop */}
                <button
                  type="button"
                  onClick={() => setActiveModal("emergency-stop")}
                  className="flex-1 sm:flex-initial flex items-center justify-center gap-2 px-3.5 py-2 text-xs font-bold rounded-lg bg-bear/20 hover:bg-bear/30 text-bear border border-bear/40 transition-all active:scale-95"
                >
                  <AlertOctagon className="w-3.5 h-3.5" />
                  <span>Emergency Stop</span>
                </button>
              </>
            ) : (
              /* Automatic or Emergency Halt State */
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveModal("reset")}
                  className={cn(
                    "flex items-center justify-center gap-2 px-4 py-2 text-xs font-bold rounded-lg transition-all shadow-md active:scale-95",
                    canReset
                      ? "bg-accent hover:bg-accent/90 text-white shadow-accent/25 hover:shadow-accent/40"
                      : "bg-surface-3 text-text-muted border border-surface-3 cursor-not-allowed opacity-80"
                  )}
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                  <span>Reset Safety Halt</span>
                  {!canReset && <Lock className="w-3 h-3 ml-1 text-bear" />}
                </button>

                {!canReset && (
                  <span className="text-2xs text-text-muted italic px-1 text-center sm:text-left">
                    Requires <code className="text-bear font-mono">risk_officer</code> role
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Confirmation Modal */}
      {activeModal && (
        <KillSwitchModal
          action={activeModal}
          isOpen={true}
          onClose={() => setActiveModal(null)}
          onConfirm={handleAction}
          loading={submitting}
          canReset={canReset}
        />
      )}
    </>
  );
}
