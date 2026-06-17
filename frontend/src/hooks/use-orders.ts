"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { orderService } from "@/services/order.service";
import { useWebSocket } from "./use-websocket";
import { useCallback } from "react";
import type { WSEvent, Order } from "@/types";

export function useOrders(filters = {}) {
  return useQuery({
    queryKey: ["orders", filters],
    queryFn: () => orderService.list(filters),
  });
}

export function useOrderMutations() {
  const qc = useQueryClient();

  const cancel = useMutation({
    mutationFn: (id: string) => orderService.cancel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orders"] }),
  });

  return { cancel };
}

export function useOrderLiveUpdates() {
  const qc = useQueryClient();

  const handler = useCallback(
    (_event: WSEvent<Order>) => {
      qc.invalidateQueries({ queryKey: ["orders"] });
    },
    [qc]
  );

  useWebSocket<Order>("order.new", handler);
  useWebSocket<Order>("order.updated", handler);
}
