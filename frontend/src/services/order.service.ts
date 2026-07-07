import apiClient from "@/lib/api-client";
import type { Order, OrderListResponse } from "@/types";

export const orderService = {
  list: (params: { state?: string; limit?: number; offset?: number } = {}) =>
    apiClient
      .get<OrderListResponse>("orders", { params })
      .then((r) => r.data),

  getById: (id: string) =>
    apiClient.get<Order>(`orders/${id}`).then((r) => r.data),

  cancel: (id: string) =>
    apiClient.post<Order>(`orders/${id}/cancel`).then((r) => r.data),
};
