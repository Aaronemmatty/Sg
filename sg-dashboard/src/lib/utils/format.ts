import { format, formatDistanceToNow, parseISO } from "date-fns";

// ─── Currency ────────────────────────────────────────────────────────────────

export function formatInr(value: number, compact = false): string {
  if (compact) {
    if (Math.abs(value) >= 1_00_00_000) {
      return `₹${(value / 1_00_00_000).toFixed(2)}Cr`;
    }
    if (Math.abs(value) >= 1_00_000) {
      return `₹${(value / 1_00_000).toFixed(2)}L`;
    }
    if (Math.abs(value) >= 1_000) {
      return `₹${(value / 1_000).toFixed(1)}K`;
    }
  }
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function formatInrCompact(value: number): string {
  return formatInr(value, true);
}

// ─── Percentage ───────────────────────────────────────────────────────────────

export function formatPct(value: number, decimals = 2, showSign = false): string {
  const sign = showSign && value > 0 ? "+" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

export function formatPnlPct(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

// ─── Numbers ──────────────────────────────────────────────────────────────────

export function formatNumber(value: number, decimals = 0): string {
  return new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatBps(value: number): string {
  return `${value.toFixed(1)} bps`;
}

export function formatRatio(value: number, decimals = 2): string {
  return value.toFixed(decimals);
}

// ─── Dates ────────────────────────────────────────────────────────────────────

export function formatDate(iso: string): string {
  return format(parseISO(iso), "dd MMM yyyy");
}

export function formatDateTime(iso: string): string {
  return format(parseISO(iso), "dd MMM yyyy HH:mm:ss");
}

export function formatTime(iso: string): string {
  return format(parseISO(iso), "HH:mm:ss");
}

export function formatRelative(iso: string): string {
  return formatDistanceToNow(parseISO(iso), { addSuffix: true });
}

export function formatDateShort(iso: string): string {
  return format(parseISO(iso), "dd MMM");
}

// ─── P&L colouring ───────────────────────────────────────────────────────────

export function pnlClass(value: number): string {
  if (value > 0) return "text-bull";
  if (value < 0) return "text-bear";
  return "text-text-muted";
}

export function pnlBgClass(value: number): string {
  if (value > 0) return "bg-bull/10 text-bull";
  if (value < 0) return "bg-bear/10 text-bear";
  return "bg-neutral/10 text-neutral";
}

// ─── Confidence / signal display ─────────────────────────────────────────────

export function confidenceColor(confidence: number): string {
  if (confidence >= 0.8) return "text-bull";
  if (confidence >= 0.6) return "text-accent";
  return "text-text-secondary";
}

export function directionClass(direction: "LONG" | "SHORT" | "FLAT"): string {
  switch (direction) {
    case "LONG": return "text-bull";
    case "SHORT": return "text-bear";
    default: return "text-text-muted";
  }
}
