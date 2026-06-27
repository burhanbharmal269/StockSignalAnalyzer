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
