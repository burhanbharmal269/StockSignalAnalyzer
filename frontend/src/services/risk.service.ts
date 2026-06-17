import apiClient from "@/lib/api-client";
import type { RiskProfile, RiskProfileListResponse, RiskDecisionListResponse } from "@/types";

export const riskService = {
  listProfiles: () =>
    apiClient
      .get<RiskProfileListResponse>("/risk-profiles")
      .then((r) => r.data.profiles),

  getActiveProfile: () =>
    apiClient.get<RiskProfile>("/risk-profiles/active").then((r) => r.data),

  getProfile: (id: string) =>
    apiClient.get<RiskProfile>(`/risk-profiles/${id}`).then((r) => r.data),

  createProfile: (data: Partial<RiskProfile>) =>
    apiClient.post<RiskProfile>("/risk-profiles", data).then((r) => r.data),

  activateProfile: (id: string) =>
    apiClient
      .post<RiskProfile>(`/risk-profiles/${id}/activate`)
      .then((r) => r.data),

  deactivateProfile: (id: string) =>
    apiClient
      .post<RiskProfile>(`/risk-profiles/${id}/deactivate`)
      .then((r) => r.data),

  // Risk decisions endpoint not yet implemented — returns empty list
  listDecisions: (_params: Record<string, unknown> = {}): Promise<RiskDecisionListResponse> =>
    Promise.resolve({ items: [], total: 0 }),
};
