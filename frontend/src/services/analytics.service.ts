import apiClient from "@/lib/api-client";

export interface ExecutionSummary {
  symbol: string | null;
  broker_name: string | null;
  period_start: string | null;
  period_end: string | null;
  record_count: number;
  avg_broker_submit_latency_ms: number | null;
  avg_fill_latency_ms: number | null;
  avg_e2e_latency_ms: number | null;
  avg_slippage_bps: number | null;
  avg_hold_seconds: number | null;
  total_pnl: number | null;
  win_count: number;
  loss_count: number;
  win_rate: number;
}

export interface ExecutionRecord {
  analytics_id: number;
  broker_name: string;
  symbol: string;
  broker_submit_latency_ms: number | null;
  fill_latency_ms: number | null;
  total_e2e_latency_ms: number | null;
  slippage_bps: number | null;
  hold_seconds: number | null;
  realized_pnl: number | null;
  trading_mode: string;
  recorded_at: string;
}

export interface ExecutionRecordsResponse {
  records: ExecutionRecord[];
  total: number;
}

export interface PaperTradingReportsResponse {
  period_type: string;
  reports: unknown[];
  count: number;
}

export const analyticsService = {
  getExecutionSummary: (params: Record<string, unknown> = {}) =>
    apiClient
      .get<ExecutionSummary>("/analytics/execution/summary", { params })
      .then((r) => r.data),

  listExecutionRecords: (params: Record<string, unknown> = {}) =>
    apiClient
      .get<ExecutionRecordsResponse>("/analytics/execution/records", { params })
      .then((r) => r.data),

  getPaperTradingReports: (periodType: "DAILY" | "WEEKLY" | "MONTHLY" = "DAILY") =>
    apiClient
      .get<PaperTradingReportsResponse>(`/paper-trading/reports/${periodType}`)
      .then((r) => r.data),
};
