"use client";

import { useEffect, useState } from "react";
import { clientFetch } from "@/lib/api/client";
import { formatDateTime, formatRelative } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";
import { Shield, Users, Activity, AlertOctagon, Loader2, RefreshCw } from "lucide-react";
import toast from "react-hot-toast";
import type { User } from "@/types";

const ALL_ROLES = ["admin", "trader", "analyst", "risk_officer", "ml_engineer", "viewer"];

interface AdminUser extends User {
  created_at: string;
  last_login: string | null;
  active_sessions: number;
}

interface AuditEntry {
  audit_id: string;
  user_id: string;
  username: string;
  action: string;
  resource: string;
  ip_address: string;
  timestamp: string;
  success: boolean;
}

export function AdminContent({ user }: { user: User }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [tab, setTab] = useState<"users" | "audit" | "system">("users");
  const [loading, setLoading] = useState(true);

  async function loadData() {
    setLoading(true);
    try {
      const [usersData, auditData] = await Promise.all([
        clientFetch<AdminUser[]>("auth/admin/users"),
        clientFetch<AuditEntry[]>("auth/admin/audit?limit=50"),
      ]);
      setUsers(usersData);
      setAudit(auditData);
    } catch {
      // Auth service may not have admin endpoints — show empty gracefully
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { loadData(); }, []);

  async function toggleRole(userId: string, role: string, currentRoles: string[]) {
    const newRoles = currentRoles.includes(role)
      ? currentRoles.filter((r) => r !== role)
      : [...currentRoles, role];
    try {
      await clientFetch(`auth/admin/users/${userId}/roles`, {
        method: "PUT",
        body: JSON.stringify({ roles: newRoles }),
      });
      setUsers((prev) => prev.map((u) => u.user_id === userId ? { ...u, roles: newRoles } : u));
      toast.success("Roles updated");
    } catch {
      toast.error("Failed to update roles");
    }
  }

  async function revokeAllSessions(userId: string) {
    try {
      await clientFetch(`auth/admin/users/${userId}/sessions`, { method: "DELETE" });
      toast.success("All sessions revoked");
      loadData();
    } catch {
      toast.error("Failed to revoke sessions");
    }
  }

  async function resetCircuitBreaker() {
    try {
      await clientFetch("risk/circuit-breaker/reset", { method: "POST" });
      toast.success("Circuit breaker reset");
    } catch {
      toast.error("Failed to reset circuit breaker");
    }
  }

  async function triggerDriftCompute() {
    try {
      await clientFetch("ml/monitoring/drift/compute", { method: "POST" });
      toast.success("Drift computation triggered");
    } catch {
      toast.error("Failed to trigger drift computation");
    }
  }

  const TABS = [
    { key: "users", label: "Users & RBAC", icon: Users },
    { key: "audit", label: "Audit Log", icon: Activity },
    { key: "system", label: "System Controls", icon: AlertOctagon },
  ] as const;

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Admin badge */}
      <div className="flex items-center gap-3 p-4 bg-accent/5 border border-accent/20 rounded-lg">
        <Shield className="w-5 h-5 text-accent" />
        <div>
          <div className="text-sm font-semibold text-text-primary">Admin Panel</div>
          <div className="text-xs text-text-muted">Logged in as {user.username} · All actions are audited</div>
        </div>
        <button onClick={loadData} className="ml-auto btn-ghost p-2">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      <div className="card">
        {/* Tabs */}
        <div className="flex border-b border-border px-5">
          {TABS.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cn(
                "flex items-center gap-2 px-4 py-3.5 text-sm font-medium border-b-2 transition-colors -mb-px",
                tab === key
                  ? "border-accent text-accent"
                  : "border-transparent text-text-muted hover:text-text-secondary"
              )}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>

        {/* Users tab */}
        {tab === "users" && (
          <div className="overflow-x-auto">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-5 h-5 animate-spin text-accent" />
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Roles</th>
                    <th className="text-right">Sessions</th>
                    <th className="text-right">Last Login</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.user_id}>
                      <td>
                        <div className="text-text-primary font-medium text-sm">{u.username}</div>
                        <div className="text-2xs text-text-muted">{u.email}</div>
                      </td>
                      <td>
                        <div className="flex flex-wrap gap-1">
                          {ALL_ROLES.map((role) => (
                            <button
                              key={role}
                              onClick={() => toggleRole(u.user_id, role, u.roles)}
                              className={cn(
                                "text-2xs px-2 py-0.5 rounded border transition-colors",
                                u.roles.includes(role)
                                  ? "bg-accent/10 text-accent border-accent/30"
                                  : "bg-surface-3 text-text-muted border-border hover:border-border-strong"
                              )}
                            >
                              {role}
                            </button>
                          ))}
                        </div>
                      </td>
                      <td className="text-right font-mono text-sm">{u.active_sessions}</td>
                      <td className="text-right text-2xs text-text-muted">
                        {u.last_login ? formatRelative(u.last_login) : "Never"}
                      </td>
                      <td className="text-right">
                        <button
                          onClick={() => revokeAllSessions(u.user_id)}
                          className="text-2xs text-bear hover:text-bear/80 transition-colors"
                          disabled={u.user_id === user.user_id}
                        >
                          Revoke sessions
                        </button>
                      </td>
                    </tr>
                  ))}
                  {!loading && users.length === 0 && (
                    <tr>
                      <td colSpan={5} className="text-center py-8 text-text-muted text-sm">
                        No users found. Auth service admin endpoints may not be available.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* Audit tab */}
        {tab === "audit" && (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>User</th>
                  <th>Action</th>
                  <th>Resource</th>
                  <th>IP</th>
                  <th className="text-right">Result</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((e) => (
                  <tr key={e.audit_id}>
                    <td className="text-2xs text-text-muted font-mono whitespace-nowrap">
                      {formatDateTime(e.timestamp)}
                    </td>
                    <td className="text-xs font-medium text-text-primary">{e.username}</td>
                    <td className="text-xs font-mono text-text-secondary">{e.action}</td>
                    <td className="text-xs text-text-muted font-mono">{e.resource}</td>
                    <td className="text-2xs text-text-muted font-mono">{e.ip_address}</td>
                    <td className="text-right">
                      <span className={cn("badge text-2xs", e.success ? "badge-bull" : "badge-bear")}>
                        {e.success ? "OK" : "FAIL"}
                      </span>
                    </td>
                  </tr>
                ))}
                {!loading && audit.length === 0 && (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-text-muted">No audit entries</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* System controls tab */}
        {tab === "system" && (
          <div className="p-5 space-y-4">
            <div className="text-xs text-bear bg-bear/10 border border-bear/20 rounded px-3 py-2">
              These controls have immediate platform-wide effect. Use with caution.
            </div>

            {[
              {
                title: "Reset Circuit Breaker",
                desc: "Re-enables order routing after a circuit breaker trigger. Confirm risk conditions are resolved first.",
                action: resetCircuitBreaker,
                label: "Reset Circuit Breaker",
                danger: true,
              },
              {
                title: "Trigger Drift Computation",
                desc: "Manually trigger PSI drift computation across all champion models. Normally runs every 30 minutes.",
                action: triggerDriftCompute,
                label: "Run Drift Check",
                danger: false,
              },
            ].map((ctrl) => (
              <div key={ctrl.title} className="flex items-start justify-between gap-6 p-4 bg-surface-2 rounded-lg border border-border">
                <div>
                  <div className="text-sm font-semibold text-text-primary">{ctrl.title}</div>
                  <div className="text-xs text-text-muted mt-0.5 max-w-md">{ctrl.desc}</div>
                </div>
                <button
                  onClick={ctrl.action}
                  className={cn("btn shrink-0", ctrl.danger ? "btn-danger" : "btn-secondary")}
                >
                  {ctrl.label}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
