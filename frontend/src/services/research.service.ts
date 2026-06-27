import { apiClient } from "@/lib/api-client";
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
    apiClient.get(`${BASE}/health`),

  getAllCohorts: (minTrades = 5): Promise<Record<string, CohortStat[]>> =>
    apiClient.get(`${BASE}/cohorts?min_trades=${minTrades}`),

  getCohortDimension: (
    dimension: string,
    minTrades = 5,
    daysBack?: number,
  ): Promise<CohortStat[]> => {
    const params = new URLSearchParams({ min_trades: String(minTrades) });
    if (daysBack) params.set("days_back", String(daysBack));
    return apiClient.get(`${BASE}/cohorts/${dimension}?${params}`);
  },

  queryCube: (
    dimensions: string[],
    minTrades = 5,
    daysBack?: number,
  ): Promise<ResearchCubeCell[]> => {
    const params = new URLSearchParams({ min_trades: String(minTrades) });
    dimensions.forEach((d) => params.append("dimensions", d));
    if (daysBack) params.set("days_back", String(daysBack));
    return apiClient.get(`${BASE}/cube?${params}`);
  },

  getDimensions: (): Promise<{ dimensions: string[] }> =>
    apiClient.get(`${BASE}/dimensions`),

  getRecommendations: (): Promise<Recommendation[]> =>
    apiClient.get(`${BASE}/recommendations`),

  checkFreeze: (proposedChange: string): Promise<FreezePolicyResponse> =>
    apiClient.post(`${BASE}/freeze-check`, { proposed_change: proposedChange }),

  getLiveVsPaper: (daysBack = 90): Promise<LiveVsPaperComparison> =>
    apiClient.get(`${BASE}/live-vs-paper?days_back=${daysBack}`),

  getLatestWeeklyReport: (): Promise<Record<string, unknown>> =>
    apiClient.get(`${BASE}/report/weekly/latest`),

  generateWeeklyReport: (): Promise<Record<string, unknown>> =>
    apiClient.get(`${BASE}/report/weekly/generate`),

  getWeeklyHistory: (limit = 12): Promise<WeeklyReportSummary[]> =>
    apiClient.get(`${BASE}/report/weekly/history?limit=${limit}`),

  getWeeklyCsvUrl: (): string => `${BASE}/report/weekly/csv`,
};
