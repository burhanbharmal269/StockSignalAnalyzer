import apiClient from "@/lib/api-client";
import type { HealthStatus } from "@/types";

export const healthService = {
  get: () => apiClient.get<HealthStatus>("/health").then((r) => r.data),
};
