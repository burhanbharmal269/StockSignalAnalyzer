// ─── Auth ────────────────────────────────────────────────────────────────────

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  force_change: boolean;
}

export interface User {
  user_id: string;
  username: string;
  role: string;
}

// ─── Enums ───────────────────────────────────────────────────────────────────

export type SignalType = "LONG" | "SHORT" | "NEUTRAL";
export type SignalState =
  | "PENDING"
  | "SCORING"
  | "SCORED"
  | "RISK_PENDING"
  | "RISK_APPROVED"
  | "FORWARDED"
  | "EXECUTED"
  | "EXPIRED"
  | "CANCELLED"
  | "RISK_REJECTED"
  | "WEAK_SIGNAL"
  | "FAILED";

export type OrderState =
  | "PENDING"
  | "SUBMITTING"
  | "SUBMITTED"
  | "OPEN"
  | "PARTIALLY_FILLED"
  | "FILLED"
  | "CANCELLED"
  | "REJECTED"
  | "REJECTED_PRE_SUBMIT"
  | "EXPIRED";

export type PositionState = "OPEN" | "PARTIALLY_CLOSED" | "CLOSED";
export type CapitalSourceMode = "ACCOUNT" | "CONFIGURED" | "HYBRID";
export type RiskProfileType = "CONSERVATIVE" | "MODERATE" | "AGGRESSIVE" | "CUSTOM";
export type AllocationType = "GLOBAL" | "STRATEGY" | "PAPER";
export type PortfolioType = "DEFAULT" | "PAPER" | "LIVE";
export type UniverseScope = "NIFTY_ONLY" | "TOP_50_FNO" | "ALL_FNO" | "CUSTOM";
export type MarketRegime =
  | "TRENDING_BULL"
  | "TRENDING_BEAR"
  | "RANGING"
  | "VOLATILE"
  | "UNKNOWN";
export type TradingMode = "LIVE" | "PAPER";
export type ExecutionMode = "MANUAL" | "AUTOMATIC";

export interface ExecutionLockState {
  locked: boolean;
  execution_mode: ExecutionMode;
  orders_blocked: boolean;
  changed_at: string | null;
  changed_by: string | null;
  note: string | null;
  signal_generation: string;
  signal_analytics: string;
  outcome_tracking: string;
  market_data: string;
}

// ─── Signal ──────────────────────────────────────────────────────────────────
// Matches backend SignalResponse schema

export interface Signal {
  signal_id: string;
  symbol: string;
  exchange: string;
  signal_type: string;        // LONG | SHORT | NEUTRAL
  strategy_type: string;
  asset_type: string;
  regime: string;
  state: string;              // SignalState value
  confidence: number | null;
  adjusted_score: number | null;
  raw_score: number | null;
  valid_until: string;
  correlation_id: string;
  risk_rejection_reason: string;
  risk_profile_id: string | null;
  allocation_id: string | null;
  portfolio_id: string | null;
  capital_source_mode: string | null;
  created_at: string;
  entry_price: number | null;
  stop_loss_price: number | null;
  target_price: number | null;
  execution_grade: string | null;
  // Option contract recommendation
  option_type: string | null;    // "CE" | "PE"
  option_strike: number | null;
  option_expiry: string | null;
  option_symbol: string | null;
  option_entry: number | null;
  option_sl: number | null;
  option_target: number | null;
}

export interface SignalListResponse {
  signals: Signal[];
  total: number;
}

// ─── Signal Overlay (Phase 21 Decision Trace) ────────────────────────────────

export interface TraceStep {
  step: number;
  name: string;
  applied: boolean;
  conf_before: number;
  adj: number;
  conf_after: number;
  size_before: number;
  size_after: number;
  severity: string | null;
  reason: string | null;
  lock: boolean;
}

export interface DecisionTrace {
  version: string;
  base_confidence: number;
  overlays: TraceStep[];
  final_confidence: number;
  final_size_multiplier: number;
  execution_grade: string;
}

export interface SignalOverlay {
  market_context: string | null;
  market_context_adj: number | null;
  event_adj: number | null;
  regime_stability: string | null;
  regime_stability_adj: number | null;
  overlay_adjusted_confidence: number | null;
  context_size_multiplier: number | null;
  execution_grade: string | null;
  decision_trace_json: string | null;
  decision_version: string | null;
  overlay_version: string | null;
  confidence: number | null;
  adjusted_score: number | null;
  was_accepted: boolean | null;
  rejection_reason: string | null;
  // Phase 24 Exit Intelligence
  expected_underlying_move_pct: number | null;
  expected_option_move_pct: number | null;
  expected_holding_minutes: number | null;
  reach_prob_json: string | null;
  recommended_target_pct: number | null;
  recommended_stop_pct: number | null;
  recommended_holding_minutes: number | null;
  target_confidence: number | null;
  configured_target_pct: number | null;
  configured_sl_pct: number | null;
  target_realism_pct: number | null;
  expiry_reason: string | null;
  expiry_snapshot_json: string | null;
  option_efficiency_score: number | null;
  delta_efficiency: number | null;
  time_in_profit_minutes: number | null;
  time_in_loss_minutes: number | null;
  time_near_target_minutes: number | null;
}

// ─── Validation (Phase 22) ───────────────────────────────────────────────────

export interface ReadinessCheck {
  points: number;
  max: number;
  status?: string;
  [key: string]: unknown;
}

export interface ReadinessCategory {
  score: number;
  max: number;
  checks: Record<string, ReadinessCheck>;
}

export interface DeploymentReadiness {
  total_score: number;
  max_score: number;
  tier: "NOT_READY" | "LIMITED" | "READY_FOR_SMALL_CAPITAL" | "READY_FOR_SCALING";
  categories: {
    infrastructure:    ReadinessCategory;
    strategy:          ReadinessCategory;
    execution_quality: ReadinessCategory;
    risk:              ReadinessCategory;
    data_quality:      ReadinessCategory;
  };
  evaluated_at: string;
}

export interface GateCriterion {
  criterion: string;
  required:  string;
  actual:    string | number;
  passed:    boolean;
}

export interface GoNoGoGate {
  gate:        string;
  label:       string;
  passed:      boolean;
  criteria:    GateCriterion[];
  explanation: string;
}

export interface GoNoGo {
  current_gate:   string | null;
  recommendation: string;
  gates:          GoNoGoGate[];
  trade_stats:    {
    n:             number;
    wins:          number;
    losses:        number;
    win_rate_pct:  number;
    profit_factor: number | null;
  };
  evaluated_at: string;
}

export interface BugCheck {
  pattern:        string;
  detected:       boolean;
  severity:       "OK" | "MEDIUM" | "HIGH" | "UNKNOWN";
  description:    string;
  evidence:       Record<string, unknown>;
  recommendation: string;
}

export interface BugDetection {
  summary: {
    total_checks:  number;
    detected:      number;
    high_severity: number;
    system_healthy: boolean;
    sample_window: number;
  };
  checks:       BugCheck[];
  evaluated_at: string;
}

export interface DriftCheck {
  metric:       string;
  reference:    number | null;
  comparison:   number | null;
  pct_change:   number | null;
  z_stat:       number;
  significance: "SIGNIFICANT" | "NOT_SIGNIFICANT" | "INSUFFICIENT_DATA";
  direction:    "IMPROVED" | "DEGRADED" | "UNCHANGED";
}

export interface ProductionDrift {
  periods: {
    reference:  { start: string; end: string; days: number };
    comparison: { start: string; end: string; days: number };
  };
  drift_checks: DriftCheck[];
  summary: {
    total_checks:       number;
    significant_drifts: number;
    system_stable:      boolean;
  };
  evaluated_at: string;
}

export interface ValidationHealthSummary {
  overall:        "HEALTHY" | "NEEDS_ATTENTION" | "CRITICAL";
  tier:           string;
  score:          number;
  gate:           string | null;
  issues:         string[];
  warnings:       string[];
  recommendation: string;
}

export interface ValidationSummaryReport {
  report_type:          "SUMMARY";
  generated_at:         string;
  health_summary:       ValidationHealthSummary;
  deployment_readiness: DeploymentReadiness;
  go_no_go:             GoNoGo;
  bug_detection:        BugDetection;
}

// ─── Phase 23 — Research Operating Model ─────────────────────────────────────

export interface CohortStat {
  cohort:          string;
  trade_count:     number;
  win_rate:        number;
  profit_factor:   number | null;
  expectancy:      number | null;
  sharpe:          number | null;
  sortino:         number | null;
  avg_mfe:         number | null;
  avg_mae:         number | null;
  avg_score:       number;
  avg_confidence:  number;
  avg_data_quality:number;
}

export interface CohortDimensionSummary {
  top:                      CohortStat[];
  bottom:                   CohortStat[];
  total_cohorts_with_data:  number;
}

export interface ResearchCubeCell {
  [dimension: string]:  string | number | null;
  trade_count:          number;
  win_rate:             number;
  profit_factor:        number | null;
  expectancy:           number | null;
  sharpe:               number | null;
}

export interface Recommendation {
  id:                   number | null;
  recommendation_type:  string;
  dimension:            string;
  cohort_key:           string | null;
  direction:            string;
  trade_count:          number;
  z_statistic:          number | null;
  p_value:              number | null;
  ci_low:               number | null;
  ci_high:              number | null;
  cohort_win_rate:      number;
  baseline_win_rate:    number;
  cohort_pf:            number | null;
  status:               "WAIT" | "EMERGING" | "READY_FOR_REVIEW" | "APPROVED" | "REJECTED" | "INSUFFICIENT_DATA";
  expected_improvement: string | null;
  risk_description:     string | null;
  rollback_plan:        string | null;
  generated_at:         string;
  message?:             string;
}

export interface FreezePolicyResponse {
  status:            "ALLOWED" | "ARCHITECTURE_FROZEN";
  completed_trades:  number;
  minimum_required:  number;
  proposed_change:   string;
  message:           string;
  requirements:      Record<string, unknown>;
  evaluated_at:      string;
}

export interface LiveVsPaperStats {
  n:                number;
  win_rate:         number;
  profit_factor:    number | null;
  expectancy:       number | null;
  avg_data_quality: number;
  ab_grade_pct:     number;
  worst_trade_pct:  number | null;
  pnl_stddev:       number | null;
}

export interface LvpDriftCheck {
  metric:      string;
  paper:       number | null;
  live:        number | null;
  delta:       number | null;
  direction:   "IMPROVED" | "DEGRADED" | "UNCHANGED" | "UNKNOWN";
  significant: boolean;
  z_statistic: number | null;
}

export interface LiveVsPaperComparison {
  paper:        LiveVsPaperStats;
  live:         LiveVsPaperStats;
  drift_checks: LvpDriftCheck[];
  period_days:  number;
  has_live_data:boolean;
  evaluated_at: string;
}

export interface HealthCategory {
  score:   number;
  weight:  number;
  details: Record<string, unknown>;
}

export interface StrategyHealth {
  overall:      number;
  trend:        "IMPROVING" | "STABLE" | "DECLINING";
  categories:   Record<string, HealthCategory>;
  evaluated_at: string;
}

export interface WeeklyReportSummary {
  week_start:     string;
  week_end:       string;
  created_at:     string | null;
  overall_health: number | null;
}

// ─── Order ───────────────────────────────────────────────────────────────────
// Matches backend OrderResponse schema

export interface Order {
  order_id: string;
  signal_id: string | null;
  tradingsymbol: string;
  symbol: string;
  exchange: string;
  transaction_type: string;   // BUY | SELL
  order_type: string;
  product: string;
  quantity: number;
  lots: number;
  limit_price: number | null;
  trigger_price: number | null;
  state: string;              // OrderState value
  broker_order_id: string;
  filled_quantity: number;
  average_fill_price: number | null;
  rejection_reason: string;
  trading_mode: string;       // LIVE | PAPER
  created_at: string;
  updated_at: string;
}

export interface OrderListResponse {
  orders: Order[];
  total: number;
}

// ─── Position ────────────────────────────────────────────────────────────────
// Matches backend PositionResponse schema

export interface Position {
  position_id: string;
  signal_id: string | null;
  order_id: string | null;
  symbol: string;
  exchange: string;
  direction: string;          // LONG | SHORT | NEUTRAL
  quantity: number;
  entry_price: number;
  current_price: number;
  state: string;              // PositionState value
  realized_pnl: number;
  current_mtm_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  trading_mode: string;       // LIVE | PAPER
  opened_at: string;
  closed_at: string | null;
}

export interface PositionListResponse {
  positions: Position[];
  total: number;
}

// ─── Risk ─────────────────────────────────────────────────────────────────────
// Matches backend RiskProfileResponse schema

export interface RiskProfile {
  profile_id: string;
  name: string;
  profile_type: string;       // RiskProfileType value
  universe_scope: string;     // UniverseScope value
  risk_per_trade_pct: number;
  max_open_positions: number;
  daily_loss_pct: number;
  weekly_loss_pct: number;
  drawdown_pct: number;
  max_position_size_pct: number;
  min_position_size_lots: number;
  is_active: boolean;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface RiskProfileListResponse {
  profiles: RiskProfile[];
  total: number;
}

export interface RiskDecision {
  id: number;
  signal_id: string;
  approved: boolean;
  rejection_code: string | null;
  rejection_reason: string | null;
  position_size_lots: number | null;
  risk_profile_id: string | null;
  allocation_id: string | null;
  portfolio_id: string | null;
  evaluated_at: string;
}

export interface RiskDecisionListResponse {
  items: RiskDecision[];
  total: number;
}

// ─── Capital Framework ───────────────────────────────────────────────────────
// Matches backend CapitalAllocationResponse schema

export interface CapitalAllocation {
  allocation_id: string;
  name: string;
  description: string;
  allocation_type: string;    // AllocationType value
  universe_scope: string;     // UniverseScope value
  allocated_capital: number;
  allocated_margin: number | null;
  strategy_type: string | null;
  capital_source_mode: string; // CapitalSourceMode value
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CapitalAllocationListResponse {
  allocations: CapitalAllocation[];
  total: number;
}

// Matches backend PortfolioResponse schema

export interface Portfolio {
  portfolio_id: string;
  name: string;
  description: string;
  portfolio_type: string;     // PortfolioType value
  risk_profile_id: string | null;
  allocation_id: string | null;
  owner_user_id: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PortfolioListResponse {
  portfolios: Portfolio[];
  total: number;
}

// Matches backend EffectiveAccountStateResponse schema

export interface EffectiveAccountState {
  capital_source_mode: string;
  broker_capital: number;
  broker_margin: number;
  configured_capital: number;
  configured_margin: number | null;
  effective_capital: number;
  effective_margin: number;
  effective_daily_loss_limit: number;
  effective_weekly_loss_limit: number;
  effective_drawdown_limit: number;
  effective_risk_per_trade: number;
  effective_max_open_positions: number;
  risk_profile_id: string | null;
  allocation_id: string | null;
  portfolio_id: string | null;
  captured_at: string;
}

// ─── Universe / Regime ───────────────────────────────────────────────────────

export interface UniverseSymbol {
  symbol: string;
  name: string;
  sector: string | null;
  is_fo: boolean;
  is_index: boolean;
}

export interface RegimeData {
  instrument_token: string;
  primary_regime: MarketRegime;
  confidence: number;
  evaluated_at: string;
}

// ─── Broker ──────────────────────────────────────────────────────────────────
// Matches backend BrokerStatusResponse schema

export interface KillSwitchState {
  is_active: boolean;
  activated_at: string | null;
  activated_by: string | null;
  activation_reason: string | null;
  deactivated_at: string | null;
  deactivated_by: string | null;
}

export type BrokerSessionStatus =
  | "CONNECTED"
  | "DISCONNECTED"
  | "AUTH_REQUIRED"
  | "SESSION_EXPIRED"
  | "ERROR";

export interface BrokerStatus {
  broker_name: string;
  status: "HEALTHY" | "DEGRADED" | "DOWN";
  session_status: BrokerSessionStatus;
  kill_switch: KillSwitchState;
  latency_ms: number;
  details: Record<string, unknown>;
  checked_at: string;
  authenticated_user: string | null;
  session_expires_at: string | null;
  session_created_at: string | null;
  market_data_status: string;
  order_placement_status: string;
  historical_data_status: string;
}

export interface TradingModeResponse {
  mode: TradingMode;
}

export interface BrokerSessionInfo {
  session_id: string;
  broker_name: string;
  is_active: boolean;
  is_expired: boolean;
  expires_at: string;
  created_at: string;
  user_name: string;
}

export interface BrokerSessionResponse {
  mode: string;
  session: BrokerSessionInfo | null;
}

export interface BrokerLoginUrl {
  login_url: string;
  mode: string;
}

// ─── System Health ───────────────────────────────────────────────────────────

export interface HealthStatus {
  status: "ok" | "degraded" | "unhealthy";
  version: string;
  environment: string;
}

// ─── WebSocket Events ────────────────────────────────────────────────────────

export type WSEventType = string;

export interface WSMessage<T = unknown> {
  type: string;
  data?: T;
}

export interface WSEvent<T = unknown> {
  type: string;
  data?: T;
}

// ─── API Error ───────────────────────────────────────────────────────────────

export interface ApiError {
  detail: string;
  status_code: number;
}
