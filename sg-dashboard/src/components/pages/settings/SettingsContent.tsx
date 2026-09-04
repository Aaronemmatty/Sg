"use client";

import { useState } from "react";
import { clientFetch } from "@/lib/api/client";
import { useBrokerStatus } from "@/hooks/use-data";
import { cn } from "@/lib/utils/cn";
import toast from "react-hot-toast";
import Link from "next/link";
import { Settings, Key, Bell, Shield, Zap, Save, AlertTriangle, ExternalLink, ShieldCheck, ShieldAlert } from "lucide-react";

function Section({ title, icon: Icon, children }: { title: string; icon: React.ElementType; children: React.ReactNode }) {
  return (
    <div className="card">
      <div className="card-header">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-accent" />
          <span className="card-title">{title}</span>
        </div>
      </div>
      <div className="p-5 space-y-4">{children}</div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-6">
      <div className="min-w-0 flex-1">
        <div className="text-sm text-text-primary font-medium">{label}</div>
        {hint && <div className="text-xs text-text-muted mt-0.5">{hint}</div>}
      </div>
      <div className="shrink-0 w-64">{children}</div>
    </div>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className={cn(
        "relative w-10 h-5 rounded-full transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-accent/40",
        checked ? "bg-accent" : "bg-surface-3"
      )}
    >
      <span className={cn(
        "absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform duration-200",
        checked ? "translate-x-5" : "translate-x-0"
      )} />
    </button>
  );
}

export function SettingsContent() {
  const { data: brokerStatus, isLoading: brokerLoading } = useBrokerStatus();
  const isLive = brokerStatus?.mode === "live";

  const [riskLimits, setRiskLimits] = useState({
    daily_loss_limit_inr: "50000",
    drawdown_limit_pct: "10",
    max_position_size_pct: "15",
    concentration_limit_pct: "70",
  });

  const [notifications, setNotifications] = useState({
    circuit_breaker: true,
    drift_alert: true,
    execution_fills: false,
    daily_summary: true,
  });

  const [saving, setSaving] = useState(false);

  async function saveSection(section: string, data: Record<string, unknown>) {
    setSaving(true);
    try {
      await clientFetch(`settings/${section}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      });
      toast.success("Settings saved");
    } catch {
      toast.error("Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-3xl space-y-5 animate-fade-in">
      {/* Broker Configuration & Mode Notice */}
      <Section title="Broker & Execution Mode" icon={Zap}>
        <div className="flex items-center justify-between p-4 rounded-lg bg-surface-2 border border-border">
          <div className="flex items-center gap-3">
            <div className={cn(
              "w-10 h-10 rounded-lg flex items-center justify-center border shrink-0",
              isLive
                ? "bg-bear/15 text-bear border-bear/30"
                : "bg-bull/15 text-bull border-bull/30"
            )}>
              {isLive ? <ShieldAlert className="w-5 h-5" /> : <ShieldCheck className="w-5 h-5" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-text-muted uppercase">Active Broker Mode</span>
                <span className={cn(
                  "px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider border",
                  isLive
                    ? "bg-bear/20 text-bear border-bear/40"
                    : "bg-bull/20 text-bull border-bull/40"
                )}>
                  {brokerLoading ? "CHECKING..." : isLive ? "LIVE REAL-MONEY TRADING" : "PAPER SIMULATION"}
                </span>
              </div>
              <p className="text-xs text-text-secondary mt-0.5">
                Broker: <span className="font-mono text-text-primary uppercase">{brokerStatus?.broker || (isLive ? "kite" : "paper")}</span>
                {brokerStatus?.connected !== undefined && (
                  <span className="ml-2 font-mono text-text-muted">
                    ({brokerStatus.connected ? "Connected" : "Disconnected"})
                  </span>
                )}
              </p>
            </div>
          </div>

          <Link
            href="/kite-auth"
            className="btn-secondary text-xs flex items-center gap-1.5 py-1.5 px-3"
          >
            <Key className="w-3.5 h-3.5" />
            <span>Kite Auth Page</span>
            <ExternalLink className="w-3 h-3 text-text-muted" />
          </Link>
        </div>

        <div className="p-4 rounded-lg bg-surface-2/50 border border-border/80 space-y-2.5">
          <div className="flex items-center gap-2 text-warning text-xs font-semibold">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>Trading Mode Configuration Notice</span>
          </div>
          <p className="text-xs text-text-secondary leading-relaxed">
            Trading mode (Paper vs. Live) and broker API credentials are read once during service startup from service environment files. Runtime toggling while services are running is permanently disabled to eliminate accidental real-capital risk.
          </p>
          <div className="bg-background/80 rounded p-3 text-2xs font-mono text-text-muted space-y-1">
            <div className="text-text-secondary font-semibold">To switch trading modes:</div>
            <div>1. Stop platform: <span className="text-accent">.\sg.ps1 stop</span></div>
            <div>2. Edit mode in: <span className="text-accent">broker_service/.env</span> (BROKER_MODE, ENABLE_REAL_MONEY_TRADING)</div>
            <div>3. Launch platform: <span className="text-accent">.\sg.ps1 start</span> (runs startup pre-flight CONFIRM gate)</div>
          </div>
        </div>
      </Section>

      {/* Risk Limits */}
      <Section title="Risk Limits" icon={Shield}>
        <div className="text-xs text-warning bg-warning/10 border border-warning/20 rounded px-3 py-2">
          Changes take effect immediately. Existing orders are not affected.
        </div>

        {[
          { key: "daily_loss_limit_inr", label: "Daily Loss Limit (₹)", hint: "Circuit breaker triggers when daily P&L hits this" },
          { key: "drawdown_limit_pct", label: "Drawdown Limit (%)", hint: "Alert when portfolio drawdown exceeds this" },
          { key: "max_position_size_pct", label: "Max Position Size (%)", hint: "Single position as % of portfolio" },
          { key: "concentration_limit_pct", label: "Top-5 Concentration Limit (%)", hint: "Max % of portfolio in top-5 holdings" },
        ].map((field) => (
          <Field key={field.key} label={field.label} hint={field.hint}>
            <input
              type="number"
              className="input"
              value={riskLimits[field.key as keyof typeof riskLimits]}
              onChange={(e) => setRiskLimits({ ...riskLimits, [field.key]: e.target.value })}
            />
          </Field>
        ))}

        <div className="flex justify-end">
          <button onClick={() => saveSection("risk", riskLimits)} disabled={saving} className="btn-primary gap-2">
            <Save className="w-3.5 h-3.5" /> Save Risk Limits
          </button>
        </div>
      </Section>

      {/* Notifications */}
      <Section title="Notifications" icon={Bell}>
        {[
          { key: "circuit_breaker", label: "Circuit Breaker Alerts", hint: "Alert when circuit breaker triggers" },
          { key: "drift_alert", label: "Model Drift Alerts", hint: "Alert when PSI drift exceeds 0.2" },
          { key: "execution_fills", label: "Order Fill Notifications", hint: "Every fill — can be noisy" },
          { key: "daily_summary", label: "Daily P&L Summary", hint: "End-of-day portfolio summary" },
        ].map((field) => (
          <Field key={field.key} label={field.label} hint={field.hint}>
            <Toggle
              checked={notifications[field.key as keyof typeof notifications]}
              onChange={(v) => setNotifications({ ...notifications, [field.key]: v })}
            />
          </Field>
        ))}

        <div className="flex justify-end">
          <button onClick={() => saveSection("notifications", notifications)} disabled={saving} className="btn-primary gap-2">
            <Save className="w-3.5 h-3.5" /> Save Notifications
          </button>
        </div>
      </Section>

      {/* Service health quick view */}
      <Section title="Service Status" icon={Settings}>
        <div className="grid grid-cols-2 gap-2">
          {[
            { name: "Auth Service", port: 8001 },
            { name: "Market Data", port: 8002 },
            { name: "Broker Service", port: 8003 },
            { name: "Strategy Service", port: 8004 },
            { name: "Regime Detection", port: 8005 },
            { name: "Orchestrator", port: 8006 },
            { name: "Risk Engine", port: 8007 },
            { name: "Execution Engine", port: 8008 },
            { name: "Portfolio Mgmt", port: 8009 },
            { name: "Backtesting", port: 8010 },
            { name: "ML Platform", port: 8011 },
            { name: "AI Analyst", port: 8012 },
          ].map((svc) => (
            <ServiceHealthRow key={svc.port} name={svc.name} port={svc.port} />
          ))}
        </div>
      </Section>
    </div>
  );
}

function ServiceHealthRow({ name, port }: { name: string; port: number }) {
  const [status, setStatus] = useState<"unknown" | "ok" | "error">("unknown");

  async function ping() {
    try {
      const res = await clientFetch<{ status: string }>(`proxy-health/${port}`);
      setStatus(res.status === "ok" ? "ok" : "error");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="flex items-center justify-between bg-surface-2 rounded px-3 py-2">
      <div>
        <div className="text-xs text-text-primary">{name}</div>
        <div className="text-2xs text-text-muted font-mono">:{port}</div>
      </div>
      <div className="flex items-center gap-2">
        <div className={cn(
          "w-2 h-2 rounded-full",
          status === "ok" ? "bg-bull" :
          status === "error" ? "bg-bear" : "bg-neutral"
        )} />
        <button onClick={ping} className="text-2xs text-text-muted hover:text-text-secondary">
          ping
        </button>
      </div>
    </div>
  );
}
