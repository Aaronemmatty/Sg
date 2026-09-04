"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Briefcase,
  ArrowLeftRight,
  Cpu,
  ShieldAlert,
  Brain,
  FlaskConical,
  Settings,
  Shield,
  LogOut,
  ChevronRight,
  Activity,
  TrendingUp,
  KeyRound,
} from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { useStore } from "@/lib/stores/app.store";
import { formatInrCompact, pnlClass } from "@/lib/utils/format";
import { usePortfolioSnapshot } from "@/hooks/use-data";
import toast from "react-hot-toast";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/portfolio", label: "Portfolio", icon: Briefcase },
  { href: "/trades", label: "Trades", icon: ArrowLeftRight },
  { href: "/strategies", label: "Strategies", icon: Cpu },
  { href: "/risk", label: "Risk", icon: ShieldAlert },
  { href: "/ml-models", label: "ML Models", icon: Brain },
  { href: "/backtesting", label: "Backtesting", icon: FlaskConical },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/kite-auth", label: "Kite Auth", icon: KeyRound },
  { href: "/admin", label: "Admin", icon: Shield },
];

export function Sidebar() {
  const pathname = usePathname();
  const user = useStore((s) => s.user);
  const circuitBreakerActive = useStore((s) => s.circuitBreakerActive);
  const { data: snapshot } = usePortfolioSnapshot();

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  }

  return (
    <aside className="flex flex-col w-56 min-h-screen bg-surface border-r border-border shrink-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-border">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded bg-accent flex items-center justify-center">
            <TrendingUp className="w-4 h-4 text-text-inverse" />
          </div>
          <div>
            <div className="text-sm font-bold text-text-primary tracking-tight">SG Trading</div>
            <div className="text-2xs text-text-muted">NSE/BSE Platform</div>
          </div>
        </div>
      </div>

      {/* Portfolio summary */}
      {snapshot && (
        <div className="px-5 py-3 border-b border-border bg-surface-2/30">
          <div className="text-2xs text-text-muted uppercase tracking-wider mb-1">Portfolio Value</div>
          <div className="text-base font-bold font-mono text-text-primary">
            {formatInrCompact(snapshot.total_value_inr)}
          </div>
          <div className={cn("text-xs font-mono", pnlClass(snapshot.day_pnl_inr))}>
            {snapshot.day_pnl_inr > 0 ? "+" : ""}
            {formatInrCompact(snapshot.day_pnl_inr)} today
          </div>
        </div>
      )}

      {/* Circuit breaker warning */}
      {circuitBreakerActive && (
        <div className="mx-3 my-2 px-3 py-2 bg-bear/10 border border-bear/30 rounded text-xs text-bear flex items-center gap-2">
          <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
          <span className="font-medium">Circuit Breaker Active</span>
        </div>
      )}

      {/* Nav */}
      <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.filter(({ href }) => {
          if (href === "/admin") return user?.roles?.includes("admin");
          if (href === "/kite-auth") {
            return user?.roles?.includes("admin") || user?.roles?.includes("risk_officer");
          }
          return true;
        }).map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded text-sm transition-all duration-150 group",
                active
                  ? "bg-accent/10 text-accent border border-accent/20"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface-2"
              )}
            >
              <Icon className={cn("w-4 h-4 shrink-0", active ? "text-accent" : "text-text-muted group-hover:text-text-secondary")} />
              <span className="font-medium">{label}</span>
              {active && <ChevronRight className="w-3 h-3 ml-auto text-accent/60" />}
            </Link>
          );
        })}
      </nav>

      {/* Live indicator */}
      <div className="px-5 py-2 border-t border-border flex items-center gap-2">
        <span className="live-dot" />
        <span className="text-2xs text-text-muted">Live</span>
        <Activity className="w-3 h-3 text-text-muted ml-auto" />
      </div>

      {/* User / logout */}
      <div className="px-3 py-3 border-t border-border">
        {user && (
          <div className="flex items-center gap-2.5 px-2 mb-2">
            <div className="w-7 h-7 rounded-full bg-surface-3 border border-border flex items-center justify-center text-xs font-bold text-accent">
              {(user.username?.[0] || user.email?.[0] || "A").toUpperCase()}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-text-primary truncate">{user.username || user.email || "Admin User"}</div>
              <div className="text-2xs text-text-muted truncate">{user.roles?.[0] ?? "trader"}</div>
            </div>
          </div>
        )}
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-2.5 px-3 py-2 rounded text-sm text-text-muted hover:text-bear hover:bg-bear/5 transition-colors"
        >
          <LogOut className="w-4 h-4" />
          <span>Sign out</span>
        </button>
      </div>
    </aside>
  );
}
