"use client";

import { useState } from "react";
import { clientFetch } from "@/lib/api/client";
import { cn } from "@/lib/utils/cn";
import toast from "react-hot-toast";
import { Settings, Key, Bell, Shield, Zap, Save } from "lucide-react";

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
  const [broker, setBroker] = useState({
    mode: "paper",
    kite_api_key: "",
    kite_api_secret: "",
    max_order_value_inr: "500000",
  });

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
      {/* Broker */}
      <Section title="Broker Configuration" icon={Zap}>
        <Field label="Trading Mode" hint="Paper mode uses simulated fills, never real orders">
          <div className="flex gap-2">
            {["paper", "live"].map((mode) => (
              <button
                key={mode}
                onClick={() => setBroker({ ...broker, mode })}
                className={cn(
                  "flex-1 py-2 rounded text-sm font-medium transition-colors capitalize",
                  broker.mode === mode
                    ? mode === "live"
                      ? "bg-bear/10 text-bear border border-bear/30"
                      : "bg-accent/10 text-accent border border-accent/30"
                    : "bg-surface-2 text-text-muted border border-border hover:border-border-strong"
                )}
              >
                {mode}
              </button>
            ))}
          </div>
        </Field>

        {broker.mode === "live" && (
          <>
            <Field label="Kite API Key" hint="From your Zerodha developer console">
              <input
                type="password"
                className="input"
                placeholder="api_key_…"
                value={broker.kite_api_key}
                onChange={(e) => setBroker({ ...broker, kite_api_key: e.target.value })}
              />
            </Field>
            <Field label="Kite API Secret">
              <input
                type="password"
                className="input"
                placeholder="api_secret_…"
                value={broker.kite_api_secret}
                onChange={(e) => setBroker({ ...broker, kite_api_secret: e.target.value })}
              />
            </Field>
          </>
        )}

        <Field label="Max Single Order Value" hint="Hard limit per order in INR">
          <input
            type="number"
            className="input"
            value={broker.max_order_value_inr}
            onChange={(e) => setBroker({ ...broker, max_order_value_inr: e.target.value })}
          />
        </Field>

        <div className="flex justify-end">
          <button
            onClick={() => saveSection("broker", broker)}
            disabled={saving}
            className="btn-primary gap-2"
          >
            <Save className="w-3.5 h-3.5" /> Save Broker Settings
          </button>
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
