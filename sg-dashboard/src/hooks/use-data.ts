"use client";

import useSWR, { type SWRConfiguration } from "swr";
import { clientFetch } from "@/lib/api/client";
import type {
  PortfolioSnapshot,
  PortfolioExposure,
  PerformanceMetrics,
  PerformanceWindow,
  TradeLedgerEntry,
  Position,
  RiskMetrics,
  KillSwitchStatus,
  ModelVersion,
  TrainingJob,
  DriftReport,
  AccuracyReport,
  Strategy,
  BacktestRun,
  BacktestMetrics,
  EquityPoint,
  BacktestTrade,
  RegimeState,
  AnalystReport,
  Symbol,
  Candle,
  BrokerStatus,
} from "@/types";

const DEFAULT_SWR: SWRConfiguration = {
  refreshInterval: 10_000,
  revalidateOnFocus: true,
};

const FAST_SWR: SWRConfiguration = { refreshInterval: 2_000 };
const SLOW_SWR: SWRConfiguration = { refreshInterval: 60_000 };

// ─── Portfolio ────────────────────────────────────────────────────────────────

export function usePortfolioSnapshot() {
  return useSWR<PortfolioSnapshot>(
    "portfolio/snapshot",
    () => clientFetch("portfolio/snapshot"),
    FAST_SWR
  );
}

export function usePortfolioExposure() {
  return useSWR<PortfolioExposure>(
    "portfolio/exposure",
    () => clientFetch("portfolio/exposure"),
    DEFAULT_SWR
  );
}

export function usePortfolioPositions() {
  return useSWR<Position[]>(
    "portfolio/positions",
    () => clientFetch("portfolio/positions"),
    FAST_SWR
  );
}

export function usePerformanceMetrics(window: PerformanceWindow = "30d") {
  return useSWR<PerformanceMetrics>(
    `portfolio/performance/${window}`,
    () => clientFetch(`portfolio/performance/${window}`),
    DEFAULT_SWR
  );
}

export function useTradeLedger(page = 1, pageSize = 50) {
  return useSWR<{ items: TradeLedgerEntry[]; total: number }>(
    `portfolio/trades?page=${page}&page_size=${pageSize}`,
    () => clientFetch(`portfolio/trades?page=${page}&page_size=${pageSize}`),
    DEFAULT_SWR
  );
}

// ─── Risk ─────────────────────────────────────────────────────────────────────

export function useRiskMetrics() {
  return useSWR<RiskMetrics>(
    "risk/metrics",
    () => clientFetch("risk/metrics"),
    FAST_SWR
  );
}

export function useKillSwitchStatus() {
  return useSWR<KillSwitchStatus>(
    "risk/kill-switch/status",
    () => clientFetch("risk/kill-switch/status"),
    { refreshInterval: 5_000, revalidateOnFocus: true }
  );
}

export function useBrokerStatus() {
  return useSWR<BrokerStatus>(
    "broker/status",
    () => clientFetch("broker/status"),
    { refreshInterval: 5_000, revalidateOnFocus: true }
  );
}

// ─── Strategies ───────────────────────────────────────────────────────────────

export function useStrategies() {
  return useSWR<Strategy[]>(
    "strategies",
    () => clientFetch("strategies"),
    DEFAULT_SWR
  );
}

export function useStrategy(id: string) {
  return useSWR<Strategy>(
    id ? `strategies/${id}` : null,
    () => clientFetch(`strategies/${id}`),
    DEFAULT_SWR
  );
}

// ─── Regime ───────────────────────────────────────────────────────────────────

export function useRegimes() {
  return useSWR<RegimeState[]>(
    "regime/current",
    () => clientFetch("regime/current"),
    DEFAULT_SWR
  );
}

// ─── ML Platform ──────────────────────────────────────────────────────────────

export function useChampionModels() {
  return useSWR<ModelVersion[]>(
    "ml/registry/champions",
    () => clientFetch("ml/registry/champions"),
    DEFAULT_SWR
  );
}

export function useAllModels() {
  return useSWR<ModelVersion[]>(
    "ml/registry/models",
    () => clientFetch("ml/registry/models"),
    DEFAULT_SWR
  );
}

export function useTrainingJobs() {
  return useSWR<TrainingJob[]>(
    "ml/training/jobs",
    () => clientFetch("ml/training/jobs"),
    FAST_SWR
  );
}

export function useActiveTrainingJobs() {
  return useSWR<TrainingJob[]>(
    "ml/training/active",
    () => clientFetch("ml/training/active"),
    FAST_SWR
  );
}

export function useDriftReports() {
  return useSWR<DriftReport[]>(
    "ml/monitoring/drift",
    () => clientFetch("ml/monitoring/drift"),
    SLOW_SWR
  );
}

export function useAccuracyReports() {
  return useSWR<AccuracyReport[]>(
    "ml/monitoring/accuracy",
    () => clientFetch("ml/monitoring/accuracy"),
    DEFAULT_SWR
  );
}

// ─── Backtesting ──────────────────────────────────────────────────────────────

export function useBacktestRuns() {
  return useSWR<BacktestRun[]>(
    "backtesting/runs",
    () => clientFetch("backtesting/runs"),
    DEFAULT_SWR
  );
}

export function useBacktestMetrics(id: string) {
  return useSWR<BacktestMetrics>(
    id ? `backtesting/${id}/metrics` : null,
    () => clientFetch(`backtesting/${id}/metrics`),
    SLOW_SWR
  );
}

export function useEquityCurve(id: string) {
  return useSWR<EquityPoint[]>(
    id ? `backtesting/${id}/equity-curve` : null,
    () => clientFetch(`backtesting/${id}/equity-curve`),
    SLOW_SWR
  );
}

export function useBacktestTrades(id: string) {
  return useSWR<BacktestTrade[]>(
    id ? `backtesting/${id}/trades` : null,
    () => clientFetch(`backtesting/${id}/trades`),
    SLOW_SWR
  );
}

// ─── Market Data ──────────────────────────────────────────────────────────────

export function useSymbols() {
  return useSWR<Symbol[]>(
    "market/symbols",
    () => clientFetch("market/symbols"),
    SLOW_SWR
  );
}

export function useCandles(symbol: string, interval = "1d", limit = 252) {
  return useSWR<{ candles: Candle[] }>(
    symbol ? `market/candles/${symbol}?interval=${interval}&limit=${limit}` : null,
    () => clientFetch(`market/candles/${symbol}?interval=${interval}&limit=${limit}`),
    DEFAULT_SWR
  );
}

// ─── AI Analyst ───────────────────────────────────────────────────────────────

export function useAnalystReports() {
  return useSWR<AnalystReport[]>(
    "analyst/reports",
    () => clientFetch("analyst/reports"),
    SLOW_SWR
  );
}
