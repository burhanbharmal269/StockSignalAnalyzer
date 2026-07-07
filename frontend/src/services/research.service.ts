import apiClient from "@/lib/api-client";
import type {
  CohortStat,
  FreezePolicyResponse,
  LiveVsPaperComparison,
  Recommendation,
  ResearchCubeCell,
  StrategyHealth,
  WeeklyReportSummary,
} from "@/types";

const BASE = "/api/v1/research";

export const researchService = {
  getHealth: (): Promise<StrategyHealth> =>
    apiClient.get(`${BASE}/health`).then((r) => r.data),

  getAllCohorts: (minTrades = 5): Promise<Record<string, CohortStat[]>> =>
    apiClient.get(`${BASE}/cohorts?min_trades=${minTrades}`).then((r) => r.data),

  getCohortDimension: (
    dimension: string,
    minTrades = 5,
    daysBack?: number,
  ): Promise<CohortStat[]> => {
    const params = new URLSearchParams({ min_trades: String(minTrades) });
    if (daysBack) params.set("days_back", String(daysBack));
    return apiClient.get(`${BASE}/cohorts/${dimension}?${params}`).then((r) => r.data);
  },

  queryCube: (
    dimensions: string[],
    minTrades = 5,
    daysBack?: number,
  ): Promise<ResearchCubeCell[]> => {
    const params = new URLSearchParams({ min_trades: String(minTrades) });
    dimensions.forEach((d) => params.append("dimensions", d));
    if (daysBack) params.set("days_back", String(daysBack));
    return apiClient.get(`${BASE}/cube?${params}`).then((r) => r.data);
  },

  getDimensions: (): Promise<{ dimensions: string[] }> =>
    apiClient.get(`${BASE}/dimensions`).then((r) => r.data),

  getRecommendations: (): Promise<Recommendation[]> =>
    apiClient.get(`${BASE}/recommendations`).then((r) => r.data),

  checkFreeze: (proposedChange: string): Promise<FreezePolicyResponse> =>
    apiClient.post(`${BASE}/freeze-check`, { proposed_change: proposedChange }).then((r) => r.data),

  getLiveVsPaper: (daysBack = 90): Promise<LiveVsPaperComparison> =>
    apiClient.get(`${BASE}/live-vs-paper?days_back=${daysBack}`).then((r) => r.data),

  getLatestWeeklyReport: (): Promise<Record<string, unknown>> =>
    apiClient.get(`${BASE}/report/weekly/latest`).then((r) => r.data),

  generateWeeklyReport: (): Promise<Record<string, unknown>> =>
    apiClient.get(`${BASE}/report/weekly/generate`).then((r) => r.data),

  getWeeklyHistory: (limit = 12): Promise<WeeklyReportSummary[]> =>
    apiClient.get(`${BASE}/report/weekly/history?limit=${limit}`).then((r) => r.data),

  getWeeklyCsvUrl: (): string => `${BASE}/report/weekly/csv`,
};

// ── Phase 24: Strategy Research & Versioning ──────────────────────────────────

const R24 = "/api/v1/research";

export const strategyVersioningService = {
  list: () => apiClient.get(`${R24}/versions`).then((r) => r.data),
  get: (id: string) => apiClient.get(`${R24}/versions/${id}`).then((r) => r.data),
  create: (body: Record<string, unknown>) => apiClient.post(`${R24}/versions`, body).then((r) => r.data),
  update: (id: string, body: Record<string, unknown>) => apiClient.patch(`${R24}/versions/${id}`, body).then((r) => r.data),
};

export const optimizationService = {
  start: (body: Record<string, unknown>) => apiClient.post(`${R24}/optimization/start`, body).then((r) => r.data),
  status: (runId: string) => apiClient.get(`${R24}/optimization/${runId}/status`).then((r) => r.data),
  results: (runId: string, limit = 100, sortBy = "sharpe") =>
    apiClient.get(`${R24}/optimization/${runId}/results?limit=${limit}&sort_by=${sortBy}`).then((r) => r.data),
  best: (runId: string) => apiClient.get(`${R24}/optimization/${runId}/best`).then((r) => r.data),
};

export const walkForwardService = {
  start: (body: Record<string, unknown>) => apiClient.post(`${R24}/walk-forward/start`, body).then((r) => r.data),
  windows: (runId: string) => apiClient.get(`${R24}/walk-forward/${runId}/windows`).then((r) => r.data),
  aggregate: (runId: string) => apiClient.get(`${R24}/walk-forward/${runId}/aggregate`).then((r) => r.data),
};

export const monteCarloService = {
  start: (body: Record<string, unknown>) => apiClient.post(`${R24}/monte-carlo/start`, body).then((r) => r.data),
  results: (runId: string) => apiClient.get(`${R24}/monte-carlo/${runId}/results`).then((r) => r.data),
};

export const performanceService = {
  get: (versionId: string, lookbackDays = 252) =>
    apiClient.get(`${R24}/performance/${versionId}?lookback_days=${lookbackDays}`).then((r) => r.data),
  compare: (versionIds: string[], lookbackDays = 252) =>
    apiClient.post(`${R24}/performance/compare`, { version_ids: versionIds, lookback_days: lookbackDays }).then((r) => r.data),
};

export const correlationService = {
  get: (lookbackDays = 90) => apiClient.get(`${R24}/correlations?lookback_days=${lookbackDays}`).then((r) => r.data),
  compute: (lookbackDays = 90) => apiClient.post(`${R24}/correlations/compute?lookback_days=${lookbackDays}`).then((r) => r.data),
};

export const featureImportanceService = {
  get: () => apiClient.get(`${R24}/feature-importance`).then((r) => r.data),
  compute: (lookbackDays = 90) => apiClient.post(`${R24}/feature-importance/compute?lookback_days=${lookbackDays}`).then((r) => r.data),
};

export const regimePerformanceService = {
  get: (lookbackDays = 90, versionId?: string) => {
    const params = new URLSearchParams({ lookback_days: String(lookbackDays) });
    if (versionId) params.set("version_id", versionId);
    return apiClient.get(`${R24}/regime-performance?${params}`).then((r) => r.data);
  },
  compute: (lookbackDays = 90) => apiClient.post(`${R24}/regime-performance/compute?lookback_days=${lookbackDays}`).then((r) => r.data),
};

export const symbolRankingService = {
  get: (limit = 50) => apiClient.get(`${R24}/symbol-rankings?limit=${limit}`).then((r) => r.data),
  compute: (lookbackDays = 90) => apiClient.post(`${R24}/symbol-rankings/compute?lookback_days=${lookbackDays}`).then((r) => r.data),
};

export const falsePositiveService = {
  get: (lookbackDays = 90) => apiClient.get(`${R24}/false-positive?lookback_days=${lookbackDays}`).then((r) => r.data),
  compute: (lookbackDays = 90) => apiClient.post(`${R24}/false-positive/compute?lookback_days=${lookbackDays}`).then((r) => r.data),
};

export const promotionService = {
  queue: () => apiClient.get(`${R24}/promotion/queue`).then((r) => r.data),
  request: (versionId: string, requestedBy?: string) =>
    apiClient.post(`${R24}/promotion/request`, { version_id: versionId, requested_by: requestedBy }).then((r) => r.data),
  approve: (promotionId: string, reviewer?: string) =>
    apiClient.post(`${R24}/promotion/${promotionId}/approve`, { reviewer }).then((r) => r.data),
  reject: (promotionId: string, reviewer?: string, reason?: string) =>
    apiClient.post(`${R24}/promotion/${promotionId}/reject`, { reviewer, reason }).then((r) => r.data),
};
