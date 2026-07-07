import apiClient from "@/lib/api-client";
import type { Signal, SignalListResponse } from "@/types";

export const signalService = {
  list: (params: { state?: string } = {}) =>
    apiClient
      .get<SignalListResponse>("signals", { params })
      .then((r) => r.data),

  getById: (id: string) =>
    apiClient.get<Signal>(`signals/${id}`).then((r) => r.data),

  approve: (id: string) =>
    apiClient.post<Signal>(`signals/${id}/approve`).then((r) => r.data),

  reject: (id: string, reason: string) =>
    apiClient
      .post<Signal>(`signals/${id}/reject`, { reason })
      .then((r) => r.data),
};
