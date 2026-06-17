"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { signalIntelligenceService } from "@/services/signal-intelligence.service";

export function useSignalSummary() {
  return useQuery({
    queryKey: ["intelligence", "signal-summary"],
    queryFn: () => signalIntelligenceService.getSignalSummary(),
    refetchInterval: 30_000,
  });
}

export function useTopSymbols(limit = 10) {
  return useQuery({
    queryKey: ["intelligence", "top-symbols", limit],
    queryFn: () => signalIntelligenceService.getTopSymbols(limit),
    refetchInterval: 60_000,
  });
}

export function useSectorBreakdown() {
  return useQuery({
    queryKey: ["intelligence", "sectors"],
    queryFn: () => signalIntelligenceService.getSectorBreakdown(),
    refetchInterval: 60_000,
  });
}

export function useStrategyLeaderboard(lookbackDays = 30) {
  return useQuery({
    queryKey: ["intelligence", "strategy-leaderboard", lookbackDays],
    queryFn: () => signalIntelligenceService.getStrategyLeaderboard(lookbackDays),
    staleTime: 300_000,
  });
}

export function useFilterAnalytics(lookbackDays = 30) {
  return useQuery({
    queryKey: ["intelligence", "filter-analytics", lookbackDays],
    queryFn: () => signalIntelligenceService.getFilterAnalytics(lookbackDays),
    staleTime: 300_000,
  });
}

export function useOutcomeCheck() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => signalIntelligenceService.triggerOutcomeCheck(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["intelligence"] });
    },
  });
}

export function useRegimePerformance(lookbackDays = 30) {
  return useQuery({
    queryKey: ["intelligence", "regime-performance", lookbackDays],
    queryFn: () => signalIntelligenceService.getRegimePerformance(lookbackDays),
    staleTime: 300_000,
  });
}

export function useLeaderboard(lookbackDays = 30) {
  return useQuery({
    queryKey: ["intelligence", "leaderboard", lookbackDays],
    queryFn: () => signalIntelligenceService.getLeaderboard(lookbackDays),
    staleTime: 300_000,
  });
}

export function useInsights(lookbackDays = 30) {
  return useQuery({
    queryKey: ["intelligence", "insights", lookbackDays],
    queryFn: () => signalIntelligenceService.getInsights(lookbackDays),
    staleTime: 300_000,
  });
}
