import apiClient from "@/lib/api-client";

// ─── Portfolio Intelligence ────────────────────────────────────────────────────

export interface PortfolioHeat {
  open_positions: number;
  used_risk_pct: number;
  daily_budget_pct: number;
  heat_pct: number;
  status: "NORMAL" | "WARNING" | "CRITICAL";
  wins_today: number;
  losses_today: number;
  closed_today: number;
  thresholds: { warning: number; critical: number };
  error?: string;
}

export interface CorrPair {
  symbol_a: string;
  symbol_b: string;
  correlation: number;
  level: "HIGH_CORRELATION" | "MEDIUM_CORRELATION" | "LOW_CORRELATION";
}

export interface SectorEntry {
  sector: string;
  count: number;
  pct: number;
  status: "CRITICAL" | "WARNING" | "OK";
}

export interface PortfolioRiskOfRuin {
  status: "INSUFFICIENT_DATA" | "NORMAL" | "ABNORMAL_DRAWDOWN";
  lookback_days?: number;
  days_in_sample?: number;
  days_needed?: number;
  days_have?: number;
  current_drawdown?: number;
  avg_historical_drawdown?: number;
  abnormal_threshold?: number;
  multiplier?: number;
  alert?: string | null;
  error?: string;
}

export interface SuccessCriterion {
  id: string;
  description: string;
  passed: boolean;
  value?: number | string | null;
  threshold?: number | string | null;
  note?: string;
}

export interface SuccessCriteria {
  all_conditions_met: boolean;
  passed_count: number;
  total_count: number;
  conditions: SuccessCriterion[];
  evaluated_at?: string;
  error?: string;
}

export interface PortfolioDashboard {
  overall_status: "HEALTHY" | "WARNING" | "CRITICAL";
  evaluated_at: string;
  correlation: {
    status?: string;
    symbol_count?: number;
    pairs?: CorrPair[];
    alert?: string | null;
    error?: string;
  };
  sector_exposure: {
    total_open_signals?: number;
    sectors?: SectorEntry[];
    alerts?: Array<{ sector: string; pct: number; status: string }>;
    thresholds?: { warning_pct: number; critical_pct: number };
    error?: string;
  };
  portfolio_heat: PortfolioHeat;
  risk_of_ruin: PortfolioRiskOfRuin;
  success_criteria: SuccessCriteria;
}

// ─── Post-Trade Intelligence ───────────────────────────────────────────────────

export interface AttributionReason {
  reason: string;
  count: number;
  avg_confidence: number;
}

export interface ModelFailureClass {
  class: string;
  count: number;
}

export interface QualityDistributionEntry {
  category: string;
  count: number;
  avg_quality_score: number;
}

export interface AttributionSummary {
  lookback_days: number;
  completed_trades: number;
  attributed_trades: number;
  attribution_coverage_pct: number;
  failure_reasons: AttributionReason[];
  success_reasons: AttributionReason[];
  model_failure_classes: ModelFailureClass[];
  quality_distribution: QualityDistributionEntry[];
  evaluated_at: string;
  error?: string;
}

// ─── Trade Journey ─────────────────────────────────────────────────────────────

export interface JourneyProfile {
  total_accepted?: number;
  win_count?: number;
  loss_count?: number;
  win_avg_mfe?: number | null;
  win_avg_mae?: number | null;
  win_med_mfe?: number | null;
  win_med_mae?: number | null;
  win_avg_time_to_target?: number | null;
  win_p25_time_to_target?: number | null;
  win_p75_time_to_target?: number | null;
  loss_avg_mfe?: number | null;
  loss_avg_mae?: number | null;
  loss_med_mfe?: number | null;
  loss_med_mae?: number | null;
  loss_avg_time_to_stop?: number | null;
  loss_p25_time_to_stop?: number | null;
  loss_p75_time_to_stop?: number | null;
  error?: string;
}

export interface StopBucket {
  bucket: string;
  count: number;
  pct: number;
  avg_mae?: number | null;
}

export interface StopDistribution {
  total_losses?: number;
  buckets?: StopBucket[];
  error?: string;
}

export interface RecoveryAnalysis {
  total_stopped?: number;
  recovered_count?: number;
  recovery_rate_pct?: number | null;
  avg_time_to_recovery_minutes?: number | null;
  error?: string;
}

export interface EntryExitSummary {
  lookback_days: number;
  trade_journey: JourneyProfile;
  stop_distribution: StopDistribution;
  recovery_analysis: RecoveryAnalysis;
  evaluated_at: string;
}

// ─── Component Attribution ─────────────────────────────────────────────────────

export interface ComponentPerformance {
  component: string;
  winner_avg: number | null;
  loser_avg: number | null;
  discriminative_power: number | null;
  verdict: "STRONG" | "WEAK" | "NEUTRAL" | "INSUFFICIENT_DATA";
}

export interface ComponentAttributionResult {
  component_performance?: ComponentPerformance[];
  regime_breakdown?: Record<string, unknown>;
  lookback_days?: number;
  evaluated_at?: string;
  error?: string;
}

export interface GateEntry {
  gate_name: string;
  pass_count: number;
  fail_count: number;
  pass_rate_pct: number | null;
  win_rate_when_passed: number | null;
  verdict: "EFFECTIVE" | "INEFFECTIVE" | "NEUTRAL" | "INSUFFICIENT_DATA";
}

export interface GateEffectivenessResult {
  lookback_days?: number;
  gates?: GateEntry[];
  evaluated_at?: string;
  error?: string;
}

// ─── Cohorts ───────────────────────────────────────────────────────────────────

export type EdgeClass = "EDGE_DISCOVERED" | "EDGE_WEAK" | "NO_EDGE" | "INSUFFICIENT_DATA";

export interface CohortEntry {
  cohort_type: string;
  bucket: string;
  count: number;
  win_rate_pct: number | null;
  profit_factor: number | null;
  expectancy_pct: number | null;
  avg_mfe_pct: number | null;
  avg_mae_pct: number | null;
  sharpe: number | null;
  sortino: number | null;
  recovery_rate_pct: number | null;
  edge: EdgeClass;
}

export interface CohortResult {
  lookback_days: number;
  cohorts: {
    score?: CohortEntry[];
    confidence?: CohortEntry[];
    mtf?: CohortEntry[];
    regime?: CohortEntry[];
    time_window?: CohortEntry[];
    dte?: CohortEntry[];
  };
  top_10_cohorts: CohortEntry[];
  bottom_10_cohorts: CohortEntry[];
  evaluated_at: string;
}

// ─── Edge Discovery ────────────────────────────────────────────────────────────

export interface EdgeEntry {
  score_bucket: string;
  regime: string;
  mtf_cohort: string;
  count: number;
  win_rate: number | null;
  profit_factor: number | null;
  expectancy: number | null;
  avg_mfe: number | null;
  avg_mae: number | null;
  edge: EdgeClass;
}

export interface EdgeDiscoveryResult {
  lookback_days: number;
  min_trades: number;
  primary_edges: EdgeEntry[];
  time_window_edges: EdgeEntry[];
  dte_edges: EdgeEntry[];
  double_confirmation_edges: EdgeEntry[];
  top_edges: EdgeEntry[];
  worst_edges: EdgeEntry[];
  evaluated_at: string;
}

// ─── Clusters ──────────────────────────────────────────────────────────────────

export interface ClusterEntry {
  cluster_id?: string | number;
  pattern: string;
  count: number;
  loss_rate_pct?: number | null;
  win_rate_pct?: number | null;
  avg_mae?: number | null;
  avg_mfe?: number | null;
  avg_return?: number | null;
  description?: string;
  components?: string[];
}

export interface ClusterResult {
  lookback_days?: number;
  top_n?: number;
  clusters?: ClusterEntry[];
  evaluated_at?: string;
  error?: string;
}

// ─── Trade Replay ──────────────────────────────────────────────────────────────

export interface ReplayEvent {
  event_type: string;
  event_time: string;
  elapsed_minutes?: number | null;
  details?: Record<string, unknown>;
  note?: string | null;
}

export interface ReplayTimeline {
  signal_id: string;
  ticker?: string;
  direction?: string;
  outcome?: string | null;
  events: ReplayEvent[];
  event_count: number;
  error?: string;
}

export interface ReplayCoverage {
  total_accepted: number;
  signals_with_replay: number;
  signals_without_replay: number;
  coverage_pct: number;
  evaluated_at: string;
}

// ─── Operator Status ───────────────────────────────────────────────────────────

export interface RegimeMixEntry {
  regime: string;
  count: number;
  pct: number;
}

export interface OperatorStatusPanel {
  panel_type: "OPERATOR_STATUS";
  scanner_version: string;
  last_scan_time: string | null;
  next_scan_eta: string;
  scanner_uptime_note: string;
  symbols_processed_today: number;
  candidates_today: number;
  signals_generated_today: number;
  targets_hit_today: number;
  stops_hit_today: number;
  active_signals: number;
  current_regime_mix: RegimeMixEntry[];
  data_quality_score: number | null;
  execution_quality_score: number | null;
  portfolio_heat: number;
  ist_time: string;
  evaluated_at: string;
  error?: string;
}

// ─── Weekly Intelligence Report ────────────────────────────────────────────────

export interface WeeklyReport {
  lookback_days: number;
  generated_at: string;
  top_failure_reasons?: Array<{ reason: string; count: number; pct?: number }>;
  top_success_reasons?: Array<{ reason: string; count: number; pct?: number }>;
  model_failure_rate?: Record<string, number>;
  execution_failure_rate?: { total?: number; failure_count?: number; failure_rate_pct?: number };
  premium_decay_analysis?: Record<string, unknown>;
  recovery_analysis?: Record<string, unknown>;
  component_ranking?: Array<{ component: string; discriminative_power?: number | null; verdict?: string }>;
  regime_ranking?: Array<{ regime: string; win_rate?: number; profit_factor?: number; count?: number }>;
  time_window_ranking?: Array<{ window: string; win_rate?: number; count?: number }>;
  mfe_mae_summary?: {
    win_avg_mfe?: number | null;
    win_avg_mae?: number | null;
    loss_avg_mfe?: number | null;
    loss_avg_mae?: number | null;
  };
  signal_quality_distribution?: Array<{ category: string; count: number; avg_score?: number }>;
  alerts?: string[];
  error?: string;
}

// ─── Recommendations ──────────────────────────────────────────────────────────

export interface Recommendation {
  category: string;
  priority: "HIGH" | "MEDIUM" | "LOW";
  title: string;
  description: string;
  metric_value?: number | null;
  metric_label?: string | null;
}

export interface RecommendationsResult {
  lookback_days?: number;
  recommendations?: Recommendation[];
  evaluated_at?: string;
  error?: string;
}

// ─── Research Dashboard ────────────────────────────────────────────────────────

export interface ResearchDashboard {
  lookback_days: number;
  evaluated_at: string;
  cohort_summary?: Partial<CohortResult>;
  edge_summary?: Partial<EdgeDiscoveryResult>;
  cluster_summary?: Partial<ClusterResult>;
  replay_coverage?: Partial<ReplayCoverage>;
  operator_status?: Partial<OperatorStatusPanel>;
  recommendations?: Recommendation[];
  risk_analytics?: Partial<PortfolioRiskOfRuin>;
  error?: string;
}

// ─── Service ───────────────────────────────────────────────────────────────────

export const analyticsIntelligenceService = {
  // Portfolio Intelligence
  getPortfolioDashboard: () =>
    apiClient.get<PortfolioDashboard>("/analytics/portfolio/dashboard").then((r) => r.data),

  getPortfolioHeat: () =>
    apiClient.get<PortfolioHeat>("/analytics/portfolio/heat").then((r) => r.data),

  getRiskOfRuin: (lookbackDays = 90) =>
    apiClient
      .get<PortfolioRiskOfRuin>("/analytics/portfolio/risk-of-ruin", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getSuccessCriteria: (lookbackDays = 30) =>
    apiClient
      .get<SuccessCriteria>("/analytics/portfolio/success-criteria", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  // Post-Trade Intelligence
  getAttributionSummary: (lookbackDays = 30) =>
    apiClient
      .get<AttributionSummary>("/analytics/post-trade/summary", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  triggerAttributionEnrich: (limit = 200) =>
    apiClient
      .post<{ processed: number; skipped: number; errors: number }>(
        "/analytics/post-trade/enrich",
        null,
        { params: { limit } }
      )
      .then((r) => r.data),

  getEntryExitSummary: (lookbackDays = 30) =>
    apiClient
      .get<EntryExitSummary>("/analytics/journey", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getStopDistribution: (lookbackDays = 30) =>
    apiClient
      .get<StopDistribution>("/analytics/stops", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getRecoveryAnalysis: (lookbackDays = 30) =>
    apiClient
      .get<RecoveryAnalysis>("/analytics/recovery", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getComponentPerformance: (lookbackDays = 30) =>
    apiClient
      .get<ComponentAttributionResult>("/analytics/components", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getGateEffectiveness: (lookbackDays = 30) =>
    apiClient
      .get<GateEffectivenessResult>("/analytics/gates", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getRecommendations: (lookbackDays = 30) =>
    apiClient
      .get<RecommendationsResult>("/analytics/recommendations", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  // Research Intelligence — Cohorts
  getCohorts: (lookbackDays = 90) =>
    apiClient
      .get<CohortResult>("/analytics/cohorts", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  // Research Intelligence — Edge Discovery
  getEdges: (lookbackDays = 90, minTrades = 10) =>
    apiClient
      .get<EdgeDiscoveryResult>("/analytics/edges", {
        params: { lookback_days: lookbackDays, min_trades: minTrades },
      })
      .then((r) => r.data),

  // Research Intelligence — Clusters
  getLossClusters: (lookbackDays = 90, topN = 15) =>
    apiClient
      .get<ClusterResult>("/analytics/clusters/loss", {
        params: { lookback_days: lookbackDays, top_n: topN },
      })
      .then((r) => r.data),

  getWinnerClusters: (lookbackDays = 90, topN = 15) =>
    apiClient
      .get<ClusterResult>("/analytics/clusters/winners", {
        params: { lookback_days: lookbackDays, top_n: topN },
      })
      .then((r) => r.data),

  // Trade Replay
  getReplayTimeline: (signalId: string) =>
    apiClient.get<ReplayTimeline>(`/analytics/replay/${signalId}`).then((r) => r.data),

  triggerReplayBackfill: (limit = 300) =>
    apiClient
      .post<{ processed: number; succeeded: number; failed: number; events_created: number }>(
        "/analytics/replay/backfill",
        null,
        { params: { limit } }
      )
      .then((r) => r.data),

  getReplayCoverage: () =>
    apiClient.get<ReplayCoverage>("/analytics/replay/coverage").then((r) => r.data),

  // Operator
  getOperatorStatus: () =>
    apiClient.get<OperatorStatusPanel>("/analytics/operator/status").then((r) => r.data),

  // Research Dashboard
  getResearchDashboard: (lookbackDays = 30) =>
    apiClient
      .get<ResearchDashboard>("/analytics/research/dashboard", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  // Weekly Intelligence
  getWeeklyReport: (lookbackDays = 7) =>
    apiClient
      .get<WeeklyReport>("/analytics/intelligence/weekly", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),
};
