"use client";

import { useState } from "react";
import {
  useChampionModels,
  useAllModels,
  useTrainingJobs,
  useDriftReports,
  useAccuracyReports,
} from "@/hooks/use-data";
import { clientFetch } from "@/lib/api/client";
import { formatRelative, formatPct, formatDateTime } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { Brain, Play, RotateCcw, TrendingUp, AlertTriangle, CheckCircle, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import type { ModelVersion, TrainingJob } from "@/types";

const MODEL_TYPE_COLOR: Record<string, string> = {
  xgboost: "text-amber-400",
  lightgbm: "text-green-400",
  lstm: "text-blue-400",
  transformer: "text-purple-400",
};

const STATUS_BADGE: Record<string, string> = {
  champion: "badge-accent",
  challenger: "badge-neutral",
  training: "badge-warning",
  retired: "badge-neutral",
};

const JOB_STATUS_CONFIG: Record<string, { icon: React.ElementType; class: string }> = {
  pending: { icon: Loader2, class: "text-text-muted" },
  running: { icon: Loader2, class: "text-accent animate-spin" },
  completed: { icon: CheckCircle, class: "text-bull" },
  failed: { icon: AlertTriangle, class: "text-bear" },
};

function TrainingJobRow({ job }: { job: TrainingJob }) {
  const cfg = JOB_STATUS_CONFIG[job.status] ?? JOB_STATUS_CONFIG.pending;
  const Icon = cfg.icon;
  return (
    <div className="flex items-center gap-4 px-5 py-3 border-b border-border last:border-0">
      <Icon className={cn("w-4 h-4 shrink-0", cfg.class)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-text-primary">{job.symbol}</span>
          <span className={cn("text-2xs font-medium", MODEL_TYPE_COLOR[job.model_type] ?? "text-text-muted")}>
            {job.model_type}
          </span>
        </div>
        {job.status === "running" && (
          <div className="mt-1.5 h-1 bg-surface-3 rounded-full overflow-hidden w-40">
            <div
              className="h-full bg-accent rounded-full transition-all"
              style={{ width: `${job.progress_pct}%` }}
            />
          </div>
        )}
        {job.error && <div className="text-2xs text-bear mt-0.5">{job.error}</div>}
      </div>
      <div className="text-right shrink-0">
        {job.val_metric != null && (
          <div className="text-xs font-mono text-text-primary">{job.val_metric.toFixed(4)}</div>
        )}
        <div className="text-2xs text-text-muted">{formatRelative(job.started_at)}</div>
      </div>
    </div>
  );
}

function ModelRow({
  model,
  onPromote,
  onRetire,
}: {
  model: ModelVersion;
  onPromote: (id: string) => void;
  onRetire: (id: string) => void;
}) {
  return (
    <tr>
      <td className="font-mono text-text-primary">{model.symbol}</td>
      <td>
        <span className={cn("text-xs font-semibold", MODEL_TYPE_COLOR[model.model_type] ?? "text-text-muted")}>
          {model.model_type}
        </span>
      </td>
      <td>
        <span className={cn("badge text-2xs", STATUS_BADGE[model.status] ?? "badge-neutral")}>
          {model.status}
        </span>
      </td>
      <td className="text-right font-mono text-text-primary">{model.val_metric.toFixed(4)}</td>
      <td className="text-right font-mono text-text-muted">
        {model.sharpe_on_signals != null ? model.sharpe_on_signals.toFixed(2) : "—"}
      </td>
      <td className="text-right text-text-muted">{model.feature_count}</td>
      <td className="text-right text-2xs text-text-muted whitespace-nowrap">
        {formatRelative(model.trained_at)}
      </td>
      <td className="text-right">
        <div className="flex items-center justify-end gap-1">
          {model.status === "challenger" && (
            <button
              onClick={() => onPromote(model.model_id)}
              className="text-2xs btn-secondary px-2 py-1"
            >
              Promote
            </button>
          )}
          {model.status !== "retired" && (
            <button
              onClick={() => onRetire(model.model_id)}
              className="text-2xs btn-ghost px-2 py-1 text-bear hover:bg-bear/10"
            >
              Retire
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}

export function MLModelsContent() {
  const { data: champions } = useChampionModels();
  const { data: allModels, mutate: mutateModels } = useAllModels();
  const { data: jobs } = useTrainingJobs();
  const { data: driftReports } = useDriftReports();
  const { data: accuracyReports } = useAccuracyReports();

  const [activeTab, setActiveTab] = useState<"champions" | "all" | "jobs" | "drift">("champions");
  const [retraining, setRetraining] = useState(false);

  async function handleRetrainAll() {
    setRetraining(true);
    try {
      await clientFetch("ml/training/retrain-all", { method: "POST" });
      toast.success("Retrain jobs submitted for all champions");
    } catch {
      toast.error("Failed to submit retrain jobs");
    } finally {
      setRetraining(false);
    }
  }

  async function handlePromote(id: string) {
    try {
      await clientFetch(`ml/registry/promote/${id}`, { method: "POST" });
      toast.success("Model promoted to champion");
      mutateModels();
    } catch {
      toast.error("Failed to promote model");
    }
  }

  async function handleRetire(id: string) {
    try {
      await clientFetch(`ml/registry/retire/${id}`, { method: "POST" });
      toast.success("Model retired");
      mutateModels();
    } catch {
      toast.error("Failed to retire model");
    }
  }

  const driftAlerts = driftReports?.filter((d) => d.alert) ?? [];

  const TABS = [
    { key: "champions", label: "Champions", count: champions?.length, alert: false },
    { key: "all", label: "All Models", count: allModels?.length, alert: false },
    { key: "jobs", label: "Training Jobs", count: jobs?.filter((j) => j.status === "running").length, alert: false },
    { key: "drift", label: "Drift Monitor", count: driftAlerts.length, alert: driftAlerts.length > 0 },
  ] as const;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* KPIs */}
      <div className="grid grid-cols-4 gap-4">
        <div className="card p-5">
          <div className="metric-label mb-1">Champion Models</div>
          <div className="metric-value text-accent">{champions?.length ?? "—"}</div>
          <div className="text-2xs text-text-muted mt-1">Across all symbols</div>
        </div>
        <div className="card p-5">
          <div className="metric-label mb-1">Avg Val Metric</div>
          <div className="metric-value">
            {champions && champions.length > 0
              ? (champions.reduce((s, m) => s + m.val_metric, 0) / champions.length).toFixed(4)
              : "—"}
          </div>
        </div>
        <div className="card p-5">
          <div className="metric-label mb-1">Running Jobs</div>
          <div className="metric-value">{jobs?.filter((j) => j.status === "running").length ?? 0}</div>
        </div>
        <div className="card p-5">
          <div className="metric-label mb-1">Drift Alerts</div>
          <div className={cn("metric-value", driftAlerts.length > 0 ? "text-warning" : "")}>
            {driftAlerts.length}
          </div>
          {driftAlerts.length > 0 && <div className="text-2xs text-warning mt-1">PSI &gt; 0.2 detected</div>}
        </div>
      </div>

      {/* Tab navigation */}
      <div className="card">
        <div className="flex items-center justify-between px-5 pt-4 pb-0 border-b border-border">
          <div className="flex gap-0">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-3 text-sm font-medium border-b-2 transition-colors -mb-px",
                  activeTab === tab.key
                    ? "border-accent text-accent"
                    : "border-transparent text-text-muted hover:text-text-secondary"
                )}
              >
                {tab.label}
                {tab.count != null && tab.count > 0 && (
                  <span className={cn(
                    "text-2xs px-1.5 py-0.5 rounded-full font-medium",
                    tab.alert ? "bg-warning/20 text-warning" : "bg-surface-3 text-text-muted"
                  )}>
                    {tab.count}
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 mb-2">
            <button
              onClick={handleRetrainAll}
              disabled={retraining}
              className="btn-secondary text-xs px-3 py-1.5 flex items-center gap-1.5"
            >
              <RotateCcw className={cn("w-3.5 h-3.5", retraining && "animate-spin")} />
              Retrain All
            </button>
          </div>
        </div>

        {/* Champions tab */}
        {activeTab === "champions" && (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th className="text-right">Val Metric</th>
                  <th className="text-right">Sharpe</th>
                  <th className="text-right">Features</th>
                  <th className="text-right">Trained</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {champions?.map((m) => (
                  <ModelRow key={m.model_id} model={m} onPromote={handlePromote} onRetire={handleRetire} />
                ))}
                {!champions?.length && (
                  <tr><td colSpan={8} className="text-center py-8 text-text-muted">No champion models</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* All models tab */}
        {activeTab === "all" && (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th className="text-right">Val Metric</th>
                  <th className="text-right">Sharpe</th>
                  <th className="text-right">Features</th>
                  <th className="text-right">Trained</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {allModels?.map((m) => (
                  <ModelRow key={m.model_id} model={m} onPromote={handlePromote} onRetire={handleRetire} />
                ))}
                {!allModels?.length && (
                  <tr><td colSpan={8} className="text-center py-8 text-text-muted">No models</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Training jobs tab */}
        {activeTab === "jobs" && (
          <div>
            {jobs?.length ? (
              jobs.map((j) => <TrainingJobRow key={j.job_id} job={j} />)
            ) : (
              <div className="py-12 text-center text-sm text-text-muted">No training jobs</div>
            )}
          </div>
        )}

        {/* Drift tab */}
        {activeTab === "drift" && (
          <div className="p-5 space-y-4">
            {/* Accuracy summary */}
            {accuracyReports && accuracyReports.length > 0 && (
              <div>
                <div className="text-xs text-text-muted uppercase tracking-wider mb-3">Rolling Accuracy</div>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                  {accuracyReports.map((r) => (
                    <div key={r.model_id} className="bg-surface-2 rounded p-3">
                      <div className="text-2xs text-text-muted mb-1">{r.symbol} · {r.model_type}</div>
                      <div className={cn(
                        "text-lg font-bold font-mono",
                        r.rolling_accuracy >= 0.6 ? "text-bull" :
                        r.rolling_accuracy >= 0.5 ? "text-warning" : "text-bear"
                      )}>
                        {formatPct(r.rolling_accuracy * 100)}
                      </div>
                      <div className="text-2xs text-text-muted mt-0.5">{r.total_predictions} predictions</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Drift reports */}
            <div>
              <div className="text-xs text-text-muted uppercase tracking-wider mb-3">PSI Drift Reports</div>
              {driftReports?.length ? (
                <div className="space-y-3">
                  {driftReports.map((d) => (
                    <div
                      key={d.model_id}
                      className={cn(
                        "rounded-lg p-4 border",
                        d.alert
                          ? "bg-warning/5 border-warning/30"
                          : "bg-surface-2 border-border"
                      )}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          {d.alert && <AlertTriangle className="w-3.5 h-3.5 text-warning" />}
                          <span className="text-sm font-semibold text-text-primary">{d.symbol}</span>
                          <span className="text-xs text-text-muted">{formatRelative(d.computed_at)}</span>
                        </div>
                        <div className="flex gap-4 text-xs font-mono">
                          <span className="text-text-muted">Max PSI: <span className={cn(d.max_psi > 0.2 ? "text-warning" : "text-text-primary")}>{d.max_psi.toFixed(3)}</span></span>
                          <span className="text-text-muted">Avg PSI: <span className="text-text-primary">{d.avg_psi.toFixed(3)}</span></span>
                        </div>
                      </div>
                      {d.features_with_drift.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {d.features_with_drift.map((f) => (
                            <span key={f} className="text-2xs bg-warning/10 text-warning px-2 py-0.5 rounded font-mono">
                              {f}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-8 text-center text-sm text-text-muted">No drift reports available</div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
