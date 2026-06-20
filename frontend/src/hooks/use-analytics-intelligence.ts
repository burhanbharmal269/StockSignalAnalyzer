"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { analyticsIntelligenceService } from "@/services/analytics-intelligence.service";

const K = "analytics";

// ─── Portfolio Intelligence ────────────────────────────────────────────────────

export function usePortfolioDashboard() {
  return useQuery({
    queryKey: [K, "portfolio", "dashboard"],
    queryFn: () => analyticsIntelligenceService.getPortfolioDashboard(),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });
}

export function usePortfolioHeat() {
  return useQuery({
    queryKey: [K, "portfolio", "heat"],
    queryFn: () => analyticsIntelligenceService.getPortfolioHeat(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

export function useRiskOfRuin(lookbackDays = 90) {
  return useQuery({
    queryKey: [K, "portfolio", "risk-of-ruin", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getRiskOfRuin(lookbackDays),
    staleTime: 300_000,
  });
}

export function useSuccessCriteria(lookbackDays = 30) {
  return useQuery({
    queryKey: [K, "portfolio", "success-criteria", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getSuccessCriteria(lookbackDays),
    staleTime: 300_000,
  });
}

// ─── Post-Trade Intelligence ───────────────────────────────────────────────────

export function useAttributionSummary(lookbackDays = 30) {
  return useQuery({
    queryKey: [K, "post-trade", "summary", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getAttributionSummary(lookbackDays),
    staleTime: 300_000,
  });
}

export function useAttributionEnrich() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (limit: number) => analyticsIntelligenceService.triggerAttributionEnrich(limit),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [K, "post-trade"] });
    },
  });
}

export function useEntryExitSummary(lookbackDays = 30) {
  return useQuery({
    queryKey: [K, "journey", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getEntryExitSummary(lookbackDays),
    staleTime: 300_000,
  });
}

export function useComponentPerformance(lookbackDays = 30) {
  return useQuery({
    queryKey: [K, "components", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getComponentPerformance(lookbackDays),
    staleTime: 300_000,
  });
}

export function useGateEffectiveness(lookbackDays = 30) {
  return useQuery({
    queryKey: [K, "gates", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getGateEffectiveness(lookbackDays),
    staleTime: 300_000,
  });
}

export function useRecommendations(lookbackDays = 30) {
  return useQuery({
    queryKey: [K, "recommendations", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getRecommendations(lookbackDays),
    staleTime: 300_000,
  });
}

// ─── Research Intelligence ─────────────────────────────────────────────────────

export function useCohorts(lookbackDays = 90) {
  return useQuery({
    queryKey: [K, "cohorts", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getCohorts(lookbackDays),
    staleTime: 600_000,
  });
}

export function useEdges(lookbackDays = 90, minTrades = 10) {
  return useQuery({
    queryKey: [K, "edges", lookbackDays, minTrades],
    queryFn: () => analyticsIntelligenceService.getEdges(lookbackDays, minTrades),
    staleTime: 600_000,
  });
}

export function useLossClusters(lookbackDays = 90) {
  return useQuery({
    queryKey: [K, "clusters", "loss", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getLossClusters(lookbackDays),
    staleTime: 600_000,
  });
}

export function useWinnerClusters(lookbackDays = 90) {
  return useQuery({
    queryKey: [K, "clusters", "winners", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getWinnerClusters(lookbackDays),
    staleTime: 600_000,
  });
}

// ─── Trade Replay ──────────────────────────────────────────────────────────────

export function useReplayTimeline(signalId: string | null) {
  return useQuery({
    queryKey: [K, "replay", signalId],
    queryFn: () => analyticsIntelligenceService.getReplayTimeline(signalId!),
    enabled: !!signalId,
    staleTime: 600_000,
  });
}

export function useReplayCoverage() {
  return useQuery({
    queryKey: [K, "replay", "coverage"],
    queryFn: () => analyticsIntelligenceService.getReplayCoverage(),
    staleTime: 300_000,
  });
}

export function useReplayBackfill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (limit: number) => analyticsIntelligenceService.triggerReplayBackfill(limit),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: [K, "replay"] });
    },
  });
}

// ─── Operator ──────────────────────────────────────────────────────────────────

export function useOperatorStatus() {
  return useQuery({
    queryKey: [K, "operator", "status"],
    queryFn: () => analyticsIntelligenceService.getOperatorStatus(),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}

// ─── Research Dashboard ────────────────────────────────────────────────────────

export function useResearchDashboard(lookbackDays = 30) {
  return useQuery({
    queryKey: [K, "research", "dashboard", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getResearchDashboard(lookbackDays),
    staleTime: 300_000,
  });
}

// ─── Weekly Report ─────────────────────────────────────────────────────────────

export function useWeeklyReport(lookbackDays = 7) {
  return useQuery({
    queryKey: [K, "weekly", lookbackDays],
    queryFn: () => analyticsIntelligenceService.getWeeklyReport(lookbackDays),
    staleTime: 600_000,
  });
}
