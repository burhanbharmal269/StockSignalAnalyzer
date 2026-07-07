import apiClient from "@/lib/api-client";
import type { Position, PositionListResponse } from "@/types";

export const positionService = {
  list: (params: Record<string, unknown> = {}) =>
    apiClient
      .get<PositionListResponse>("positions", { params })
      .then((r) => r.data),

  getById: (id: string) =>
    apiClient.get<Position>(`positions/${id}`).then((r) => r.data),

  close: (id: string, exit_price: number) =>
    apiClient
      .post<Position>(`positions/${id}/close`, { exit_price })
      .then((r) => r.data),
};
