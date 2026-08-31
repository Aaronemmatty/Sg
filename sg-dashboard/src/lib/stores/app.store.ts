import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import type {
  User,
  PortfolioSnapshot,
  Position,
  ExecutionEvent,
  RiskEvent,
  RiskMetrics,
  MLSignal,
  RegimeState,
  Ticker,
  TrainingJob,
} from "@/types";

// ─── Auth slice ──────────────────────────────────────────────────────────────

interface AuthSlice {
  user: User | null;
  setUser: (user: User | null) => void;
}

// ─── Portfolio slice ──────────────────────────────────────────────────────────

interface PortfolioSlice {
  snapshot: PortfolioSnapshot | null;
  positions: Position[];
  setSnapshot: (s: PortfolioSnapshot) => void;
  updatePosition: (p: Position) => void;
}

// ─── Executions slice ────────────────────────────────────────────────────────

interface ExecutionSlice {
  recentExecutions: ExecutionEvent[];
  addExecution: (e: ExecutionEvent) => void;
}

// ─── Risk slice ───────────────────────────────────────────────────────────────

interface RiskSlice {
  metrics: RiskMetrics | null;
  recentEvents: RiskEvent[];
  circuitBreakerActive: boolean;
  setMetrics: (m: RiskMetrics) => void;
  addRiskEvent: (e: RiskEvent) => void;
}

// ─── Market slice ─────────────────────────────────────────────────────────────

interface MarketSlice {
  tickers: Record<string, Ticker>;
  regimes: Record<string, RegimeState>;
  mlSignals: Record<string, MLSignal>;
  updateTicker: (t: Ticker) => void;
  updateRegime: (r: RegimeState) => void;
  updateMlSignal: (s: MLSignal) => void;
}

// ─── ML slice ─────────────────────────────────────────────────────────────────

interface MlSlice {
  activeJobs: TrainingJob[];
  setActiveJobs: (jobs: TrainingJob[]) => void;
  updateJob: (job: TrainingJob) => void;
}

// ─── Combined store ───────────────────────────────────────────────────────────

type AppStore = AuthSlice & PortfolioSlice & ExecutionSlice & RiskSlice & MarketSlice & MlSlice;

export const useStore = create<AppStore>()(
  subscribeWithSelector((set) => ({
    // Auth
    user: null,
    setUser: (user) => set({ user }),

    // Portfolio
    snapshot: null,
    positions: [],
    setSnapshot: (snapshot) =>
      set({ snapshot, positions: snapshot.positions }),
    updatePosition: (position) =>
      set((state) => ({
        positions: state.positions.some((p) => p.symbol === position.symbol)
          ? state.positions.map((p) => (p.symbol === position.symbol ? position : p))
          : [...state.positions, position],
      })),

    // Executions
    recentExecutions: [],
    addExecution: (e) =>
      set((state) => ({
        recentExecutions: [e, ...state.recentExecutions].slice(0, 100),
      })),

    // Risk
    metrics: null,
    recentEvents: [],
    circuitBreakerActive: false,
    setMetrics: (metrics) =>
      set({ metrics, circuitBreakerActive: metrics.circuit_breaker_active }),
    addRiskEvent: (e) =>
      set((state) => ({
        recentEvents: [e, ...state.recentEvents].slice(0, 50),
        circuitBreakerActive:
          e.event_type === "CIRCUIT_BREAKER_TRIGGERED"
            ? true
            : state.circuitBreakerActive,
      })),

    // Market
    tickers: {},
    regimes: {},
    mlSignals: {},
    updateTicker: (t) =>
      set((state) => ({ tickers: { ...state.tickers, [t.symbol]: t } })),
    updateRegime: (r) =>
      set((state) => ({ regimes: { ...state.regimes, [r.symbol]: r } })),
    updateMlSignal: (s) =>
      set((state) => ({ mlSignals: { ...state.mlSignals, [s.symbol]: s } })),

    // ML
    activeJobs: [],
    setActiveJobs: (activeJobs) => set({ activeJobs }),
    updateJob: (job) =>
      set((state) => ({
        activeJobs: state.activeJobs.some((j) => j.job_id === job.job_id)
          ? state.activeJobs.map((j) => (j.job_id === job.job_id ? job : j))
          : [...state.activeJobs, job],
      })),
  }))
);

// Convenience selectors
export const selectUser = (s: AppStore) => s.user;
export const selectSnapshot = (s: AppStore) => s.snapshot;
export const selectPositions = (s: AppStore) => s.positions;
export const selectRiskMetrics = (s: AppStore) => s.metrics;
export const selectCircuitBreaker = (s: AppStore) => s.circuitBreakerActive;
export const selectRecentExecutions = (s: AppStore) => s.recentExecutions;
export const selectTickers = (s: AppStore) => s.tickers;
export const selectMlSignals = (s: AppStore) => s.mlSignals;
