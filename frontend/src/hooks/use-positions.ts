"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { positionService } from "@/services/position.service";
import { useWebSocket } from "./use-websocket";
import { useCallback } from "react";
import type { WSEvent, Position } from "@/types";

export function usePositions(filters = {}) {
  return useQuery({
    queryKey: ["positions", filters],
    queryFn: () => positionService.list(filters),
  });
}

export function usePositionMutations() {
  const qc = useQueryClient();

  const close = useMutation({
    mutationFn: ({ id, exit_price }: { id: string; exit_price: number }) =>
      positionService.close(id, exit_price),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["positions"] }),
  });

  return { close };
}

export function usePositionLiveUpdates() {
  const qc = useQueryClient();

  const handler = useCallback(
    (_event: WSEvent<Position>) => {
      qc.invalidateQueries({ queryKey: ["positions"] });
    },
    [qc]
  );

  useWebSocket<Position>("position.updated", handler);
}
