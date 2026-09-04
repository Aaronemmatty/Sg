// ─── Auth ───────────────────────────────────────────────────────────────────

export interface User {
  user_id: string;
  username: string;
  email: string;
  roles: string[];
  mfa_enabled: boolean;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: "Bearer";
  expires_in: number;
}

export interface Session {
  user: User;
  access_token: string;
  expires_at: number;
}

// ─── Market Data ────────────────────────────────────────────────────────────

export type Interval = "1m" | "3m" | "5m" | "15m" | "30m" | "1h" | "1d" | "1w";

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Ticker {
  symbol: string;
  ltp: number;
  change: number;
  change_pct: number;
  volume: number;
  timestamp: string;
}

export interface Symbol {
  symbol: string;
  name: string;
  exchange: "NSE" | "BSE";
  segment: string;
  lot_size: number;
}

// ─── Portfolio ──────────────────────────────────────────────────────────────

export interface Position {
  symbol: string;
  quantity: number;
  avg_cost_inr: number;
  ltp: number;
  market_value_inr: number;
  unrealised_pnl_inr: number;
  unrealised_pnl_pct: number;
  day_pnl_inr: number;
  weight_pct: number;
}

export interface PortfolioSnapshot {
  snapshot_id: string;
  timestamp: string;
  total_value_inr: number;
  cash_inr: number;
  invested_inr: number;
  total_pnl_inr: number;
  total_pnl_pct: number;
  day_pnl_inr: number;
  day_pnl_pct: number;
  positions: Position[];
}

export interface PortfolioExposure {
  gross_exposure_inr: number;
  net_exposure_inr: number;
  long_exposure_inr: number;
  short_exposure_inr: number;
  cash_pct: number;
  leverage: number;
}

export type PerformanceWindow = "1d" | "7d" | "30d" | "90d" | "252d" | "inception";

export interface PerformanceMetrics {
  window: PerformanceWindow;
  total_return_pct?: number | null;
  annualised_return_pct?: number | null;
  sharpe_ratio?: number | null;
  sortino_ratio?: number | null;
  max_drawdown_pct?: number | null;
  calmar_ratio?: number | null;
  alpha?: number | null;
  beta?: number | null;
  volatility_pct?: number | null;
  win_rate_pct?: number | null;
  profit_factor?: number | null;
  avg_win_inr?: number | null;
  avg_loss_inr?: number | null;
}

// ─── Trades / Orders ─────────────────────────────────────────────────────────

export type OrderAction = "BUY" | "SELL";
export type OrderState =
  | "ORDER_SUBMITTED"
  | "ACKNOWLEDGED"
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "REJECTED"
  | "CANCELLED"
  | "EXPIRED"
  | "FAILED";

export interface ExecutionEvent {
  event_type: string;
  order_id: string;
  intent_id: string;
  correlation_id: string;
  symbol: string;
  action: OrderAction;
  state: OrderState;
  quantity: number;
  filled_quantity: number;
  avg_fill_price_inr: number;
  slippage_bps: number;
  broker_order_id: string | null;
  reason: string | null;
  emitted_at: string;
}

export interface TradeLedgerEntry {
  trade_id: string;
  symbol: string;
  action: OrderAction;
  quantity: number;
  price_inr: number;
  value_inr: number;
  realised_pnl_inr: number | null;
  order_id: string;
  executed_at: string;
}

// ─── Strategies ──────────────────────────────────────────────────────────────

export type StrategyStatus = "active" | "paused" | "stopped" | "error";

export interface Strategy {
  strategy_id: string;
  name: string;
  type: string;
  status: StrategyStatus;
  symbols: string[];
  parameters: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface StrategySignal {
  signal_id: string;
  strategy_id: string;
  symbol: string;
  direction: "LONG" | "SHORT" | "FLAT";
  confidence: number;
  emitted_at: string;
}

export type KillSwitchState =
  | "NORMAL"
  | "HALTED_MANUAL"
  | "HALTED_AUTO_DRAWDOWN"
  | "HALTED_AUTO_DAILY_LOSS"
  | "HALTED_AUTO_CIRCUIT_BREAKER"
  | "EMERGENCY_STOP";

export interface KillSwitchStatus {
  state: KillSwitchState;
  reason: string | null;
  is_halted: boolean;
  actor?: string | null;
  updated_at?: string | null;
}

export interface RiskMetrics {
  var_95_inr: number;
  var_99_inr: number;
  cvar_95_inr: number;
  max_position_size_pct: number;
  concentration_top5_pct: number;
  daily_loss_limit_inr: number;
  daily_loss_used_inr: number;
  daily_loss_remaining_inr: number;
  drawdown_limit_pct: number;
  current_drawdown_pct: number;
  circuit_breaker_active: boolean;
}

export type RiskEventType =
  | "PRE_TRADE_APPROVED"
  | "PRE_TRADE_REJECTED"
  | "CIRCUIT_BREAKER_TRIGGERED"
  | "LIMIT_BREACH"
  | "DRAWDOWN_ALERT";

export interface RiskEvent {
  event_id: string;
  event_type: RiskEventType;
  symbol: string | null;
  message: string;
  severity: "info" | "warning" | "critical";
  timestamp: string;
}

// ─── Regime ──────────────────────────────────────────────────────────────────

export type RegimeLabel = "bull" | "bear" | "neutral" | "high_vol" | "low_vol";

export interface RegimeState {
  symbol: string;
  regime: RegimeLabel;
  confidence: number;
  detected_at: string;
}

// ─── ML Platform ─────────────────────────────────────────────────────────────

export type ModelType = "xgboost" | "lightgbm" | "lstm" | "transformer";
export type ModelStatus = "training" | "champion" | "challenger" | "retired";

export interface ModelVersion {
  model_id: string;
  symbol: string;
  model_type: ModelType;
  status: ModelStatus;
  val_metric: number;
  sharpe_on_signals: number | null;
  feature_count: number;
  trained_at: string;
  promoted_at: string | null;
}

export interface MLSignal {
  signal_id: string;
  symbol: string;
  direction: "LONG" | "SHORT" | "FLAT";
  confidence: number;
  model_types_used: ModelType[];
  regime_context: string | null;
  emitted_at: string;
  metadata: Record<string, unknown>;
}

export interface MLRegime {
  symbol: string;
  bull_probability: number;
  bear_probability: number;
  neutral_probability: number;
  predicted_vol_regime: "low" | "medium" | "high";
  emitted_at: string;
}

export interface TrainingJob {
  job_id: string;
  symbol: string;
  model_type: ModelType;
  status: "pending" | "running" | "completed" | "failed";
  progress_pct: number;
  val_metric: number | null;
  error: string | null;
  started_at: string;
  completed_at: string | null;
}

export interface DriftReport {
  model_id: string;
  symbol: string;
  features_with_drift: string[];
  max_psi: number;
  avg_psi: number;
  alert: boolean;
  computed_at: string;
}

export interface AccuracyReport {
  model_id: string;
  symbol: string;
  model_type: ModelType;
  rolling_accuracy: number;
  total_predictions: number;
  window_days: number;
}

// ─── Backtesting ─────────────────────────────────────────────────────────────

export type BacktestStatus = "pending" | "running" | "completed" | "failed";

export interface BacktestRun {
  backtest_id: string;
  strategy_id: string;
  strategy_name: string;
  symbol: string;
  interval: Interval;
  start_date: string;
  end_date: string;
  status: BacktestStatus;
  progress_pct: number;
  submitted_at: string;
  completed_at: string | null;
}

export interface BacktestMetrics {
  total_return_pct: number;
  annualised_return_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  calmar_ratio: number;
  win_rate_pct: number;
  profit_factor: number;
  total_trades: number;
  avg_trade_duration_days: number;
  benchmark_return_pct: number;
  alpha: number;
  beta: number;
}

export interface EquityPoint {
  timestamp: string;
  equity_inr: number;
  benchmark_inr: number;
  drawdown_pct: number;
}

export interface BacktestTrade {
  trade_id: string;
  symbol: string;
  action: OrderAction;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  pnl_inr: number | null;
  entered_at: string;
  exited_at: string | null;
}

// ─── AI Analyst ──────────────────────────────────────────────────────────────

export interface AnalystReport {
  report_id: string;
  report_type: "daily_summary" | "risk_alert" | "opportunity" | "custom";
  title: string;
  content: string;
  symbols_referenced: string[];
  generated_at: string;
}

export interface AnalystQuery {
  query: string;
  context?: Record<string, unknown>;
}

export interface AnalystResponse {
  response_id: string;
  query: string;
  response: string;
  data_sources: string[];
  generated_at: string;
}

// ─── SSE Events ──────────────────────────────────────────────────────────────

export interface SSEEvent<T = unknown> {
  type: string;
  data: T;
  timestamp: string;
}

// ─── API Wrappers ────────────────────────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface ApiError {
  detail: string;
  status: number;
}

// ─── Broker ──────────────────────────────────────────────────────────────────

export interface BrokerStatus {
  broker: string;
  mode: "paper" | "live";
  connected: boolean;
  circuit_breaker?: Record<string, unknown> | null;
  rate_limiter?: Record<string, unknown> | null;
}

