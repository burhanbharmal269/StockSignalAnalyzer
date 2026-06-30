import apiClient from "@/lib/api-client";

export interface TmiSummary {
  period_days: number;
  total_accepted: number;
  signals_with_mfe: number;
  positive_entry_count: number;
  positive_entry_rate: number;
  avg_mfe_pct: number;
  avg_capture_ratio: number;
  avg_profit_surrendered_pct: number;
  avg_opportunity_lost_pct: number;
  profit_tiers: {
    mfe_gte_10pct: number;
    mfe_gte_20pct: number;
    mfe_gte_30pct: number;
    mfe_gte_40pct: number;
    mfe_gte_50pct: number;
  };
  classifications: {
    BAD_ENTRY: number;
    GOOD_ENTRY_POOR_EXIT: number;
    GOOD_ENTRY_UNREALISTIC_TARGET: number;
    GOOD_ENTRY_PREMIUM_DECAY: number;
    GOOD_ENTRY_REGIME_REVERSAL: number;
    GOOD_ENTRY_CAPTURED: number;
  };
}

export interface TmiSignal {
  ticker: string;
  direction: string;
  regime: string | null;
  mfe_pct: number | null;
  mae_pct: number | null;
  current_return_pct: number | null;
  capture_ratio: number | null;
  profit_surrender_pct: number | null;
  trade_classification: string | null;
  option_symbol: string | null;
  created_ist: string;
}

export interface CaptureRatioDistribution {
  days: number;
  below_zero: number;
  zero_to_25pct: number;
  "25_to_50pct": number;
  "50_to_75pct": number;
  "75_to_100pct": number;
  full_or_above: number;
}

export interface RegimeAnalysis {
  regime: string;
  total: number;
  had_positive: number;
  avg_mfe: number | null;
  avg_surrender: number | null;
  avg_capture: number | null;
  reversals: number;
}

export interface WeeklyReport extends TmiSummary {
  week_ending: string;
  lookback_days: number;
  generated_at: string;
  capture_ratio_distribution: CaptureRatioDistribution;
  profit_surrender_analysis: {
    signals_surrendered_5pct_plus: number;
    signals_surrendered_10pct_plus: number;
    signals_surrendered_20pct_plus: number;
    avg_surrender_nonzero_pct: number;
  };
  regime_analysis: RegimeAnalysis[];
  top_signals: TmiSignal[];
  interpretation: string[];
}

const BASE = "/api/v1/trade-management";

export const tradeManagementService = {
  getSummary: (days = 30): Promise<TmiSummary> =>
    apiClient.get(`${BASE}/summary?days=${days}`).then((r) => r.data),

  getProfitTiers: (days = 30): Promise<{ days: number; signals: TmiSignal[] }> =>
    apiClient.get(`${BASE}/profit-tiers?days=${days}`).then((r) => r.data),

  getClassifications: (
    days = 30
  ): Promise<{ days: number; classifications: TmiSummary["classifications"]; total: number }> =>
    apiClient.get(`${BASE}/classifications?days=${days}`).then((r) => r.data),

  getCaptureRatio: (days = 30): Promise<CaptureRatioDistribution> =>
    apiClient.get(`${BASE}/capture-ratio?days=${days}`).then((r) => r.data),

  getRegimeAnalysis: (
    days = 30
  ): Promise<{ days: number; regimes: RegimeAnalysis[] }> =>
    apiClient.get(`${BASE}/regime-analysis?days=${days}`).then((r) => r.data),

  getWeeklyReport: (days = 7): Promise<WeeklyReport> =>
    apiClient.get(`${BASE}/weekly-report?days=${days}`).then((r) => r.data),

  runClassification: (): Promise<{ updated: number; errors: number }> =>
    apiClient.post(`${BASE}/classify`).then((r) => r.data),

  recordPositionClose: (
    analyticsId: number,
    exitPrice: number,
    closedAt?: string
  ): Promise<{
    analytics_id: number;
    position_exit_price: number;
    position_return_pct: number | null;
    capture_ratio: number | null;
  }> =>
    apiClient
      .post(`${BASE}/signals/${analyticsId}/close`, {
        exit_price: exitPrice,
        closed_at: closedAt ?? null,
      })
      .then((r) => r.data),
};
