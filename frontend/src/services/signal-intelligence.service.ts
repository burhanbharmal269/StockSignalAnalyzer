import apiClient from "@/lib/api-client";

export interface SignalSummary {
  total: number;
  accepted: number;
  rejected: number;
  unique_symbols: number;
  strategies_active: number;
  avg_score: number;
  avg_confidence: number;
}

export interface TopSymbol {
  ticker: string;
  sector: string | null;
  is_index: boolean;
  signal_count: number;
  avg_score: number;
  avg_confidence: number;
}

export interface SectorBreakdown {
  sector: string;
  total: number;
  accepted: number;
}

export interface StrategyMetrics {
  rank: number;
  strategy_type: string;
  signal_count: number;
  accepted_count: number;
  win_rate: number;
  profit_factor: number;
  avg_return_pct: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  expectancy: number;
  avg_holding_time_minutes: number;
  avg_score: number;
  avg_confidence: number;
  component_scores: {
    trend: number;
    volume: number;
    vwap: number;
    oi: number;
    sentiment: number;
  };
}

export interface StrategyLeaderboard {
  computed_at: string;
  lookback_days: number;
  best_strategy: string | null;
  worst_strategy: string | null;
  strategies: StrategyMetrics[];
}

export interface FilterMetrics {
  filter_name: string;
  description: string;
  signals_before: number;
  signals_after: number;
  pass_rate_pct: number;
  rejected_count: number;
  win_rate_passed: number;
  win_rate_rejected: number;
  performance_delta: number;
  verdict: "IMPROVING" | "HURTING" | "NEUTRAL" | "INSUFFICIENT_DATA";
}

export interface FilterAnalyticsReport {
  computed_at: string;
  lookback_days: number;
  total_signals_evaluated: number;
  total_signals_accepted: number;
  acceptance_rate: number;
  improving_filters: string[];
  hurting_filters: string[];
  filters: FilterMetrics[];
}

// --- Regime Performance ------------------------------------------------------

export interface RegimeStrategyMetric {
  regime: string;
  strategy_type: string;
  signal_count: number;
  win_count: number;
  loss_count: number;
  partial_count: number;
  win_rate: number;
  profit_factor: number;
  avg_return_pct: number;
  expectancy: number;
}

export interface RegimePerformanceReport {
  computed_at: string;
  lookback_days: number;
  best_per_regime: Record<string, string>;
  metrics: RegimeStrategyMetric[];
}

// --- Leaderboard -------------------------------------------------------------

export interface LeaderboardEntry {
  rank: number;
  name: string;
  signal_count: number;
  win_count: number;
  win_rate: number;
  profit_factor: number;
  avg_return_pct: number;
  expectancy: number;
}

export interface SignalLeaderboard {
  computed_at: string;
  lookback_days: number;
  symbols: LeaderboardEntry[];
  sectors: LeaderboardEntry[];
  regimes: LeaderboardEntry[];
}

// --- Optimization Insights ---------------------------------------------------

export interface Insight {
  priority: "HIGH" | "MEDIUM" | "LOW";
  category: "STRATEGY" | "FILTER" | "SYMBOL" | "REGIME";
  title: string;
  description: string;
  metric_value: number | null;
  metric_label: string | null;
}

export interface OptimizationReport {
  computed_at: string;
  lookback_days: number;
  insight_count: number;
  insights: Insight[];
}

export const signalIntelligenceService = {
  getSignalSummary: () =>
    apiClient.get<SignalSummary>("/intelligence/signals/summary").then((r) => r.data),

  getTopSymbols: (limit = 10) =>
    apiClient
      .get<{ top_symbols: TopSymbol[]; limit: number }>("/intelligence/signals/top-symbols", {
        params: { limit },
      })
      .then((r) => r.data),

  getSectorBreakdown: () =>
    apiClient
      .get<{ sectors: SectorBreakdown[] }>("/intelligence/signals/sectors")
      .then((r) => r.data),

  getStrategyLeaderboard: (lookbackDays = 30) =>
    apiClient
      .get<StrategyLeaderboard>("/intelligence/strategies/leaderboard", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getFilterAnalytics: (lookbackDays = 30) =>
    apiClient
      .get<FilterAnalyticsReport>("/intelligence/filters", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  triggerOutcomeCheck: () =>
    apiClient.post("/intelligence/outcomes/check").then((r) => r.data),

  getRegimePerformance: (lookbackDays = 30) =>
    apiClient
      .get<RegimePerformanceReport>("/intelligence/regime-performance", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getLeaderboard: (lookbackDays = 30) =>
    apiClient
      .get<SignalLeaderboard>("/intelligence/leaderboard", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),

  getInsights: (lookbackDays = 30) =>
    apiClient
      .get<OptimizationReport>("/intelligence/insights", {
        params: { lookback_days: lookbackDays },
      })
      .then((r) => r.data),
};
