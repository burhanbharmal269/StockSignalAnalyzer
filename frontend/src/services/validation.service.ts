import apiClient from "@/lib/api-client";
import type {
  BugDetection,
  DeploymentReadiness,
  GoNoGo,
  ProductionDrift,
  ValidationSummaryReport,
} from "@/types";

const BASE = "/validation";

export const validationService = {
  getReadiness: () =>
    apiClient.get<DeploymentReadiness>(`${BASE}/readiness`).then((r) => r.data),

  getMilestones: () =>
    apiClient.get<Record<string, unknown>>(`${BASE}/milestones`).then((r) => r.data),

  getConfidenceIntervals: (lookbackDays = 90) =>
    apiClient
      .get<Record<string, unknown>>(`${BASE}/confidence`, { params: { lookback_days: lookbackDays } })
      .then((r) => r.data),

  getOverlayValidation: (lookbackDays = 60) =>
    apiClient
      .get<Record<string, unknown>>(`${BASE}/overlay`, { params: { lookback_days: lookbackDays } })
      .then((r) => r.data),

  getComponentValidation: (lookbackDays = 60) =>
    apiClient
      .get<Record<string, unknown>>(`${BASE}/components`, { params: { lookback_days: lookbackDays } })
      .then((r) => r.data),

  getBugDetection: (sampleN = 100) =>
    apiClient
      .get<BugDetection>(`${BASE}/bugs`, { params: { sample_n: sampleN } })
      .then((r) => r.data),

  getDrift: (refDays = 30, cmpDays = 7) =>
    apiClient
      .get<ProductionDrift>(`${BASE}/drift`, { params: { ref_days: refDays, cmp_days: cmpDays } })
      .then((r) => r.data),

  getGoNoGo: () =>
    apiClient.get<GoNoGo>(`${BASE}/go-no-go`).then((r) => r.data),

  getSummaryReport: () =>
    apiClient.get<ValidationSummaryReport>(`${BASE}/report/summary`).then((r) => r.data),

  getFullReport: () =>
    apiClient.get<Record<string, unknown>>(`${BASE}/report/full`).then((r) => r.data),
};
