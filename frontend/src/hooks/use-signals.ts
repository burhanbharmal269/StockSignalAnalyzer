"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { signalService } from "@/services/signal.service";
import { useWebSocket } from "./use-websocket";
import { useCallback } from "react";
import type { WSEvent, Signal } from "@/types";

export function useSignals(filters = {}) {
  return useQuery({
    queryKey: ["signals", filters],
    queryFn: () => signalService.list(filters),
  });
}

export function useSignal(id: string) {
  return useQuery({
    queryKey: ["signals", id],
    queryFn: () => signalService.getById(id),
    enabled: !!id,
  });
}

export function useSignalMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["signals"] });

  const approve = useMutation({
    mutationFn: (id: string) => signalService.approve(id),
    onSuccess: invalidate,
  });

  const reject = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      signalService.reject(id, reason),
    onSuccess: invalidate,
  });

  return { approve, reject };
}

export function useSignalLiveUpdates() {
  const qc = useQueryClient();

  const handler = useCallback(
    (_event: WSEvent<Signal>) => {
      qc.invalidateQueries({ queryKey: ["signals"] });
    },
    [qc]
  );

  useWebSocket<Signal>("signal.new", handler);
  useWebSocket<Signal>("signal.updated", handler);
}
