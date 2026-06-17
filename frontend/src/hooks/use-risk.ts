"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { riskService } from "@/services/risk.service";

export function useRiskProfiles() {
  return useQuery({
    queryKey: ["risk-profiles"],
    queryFn: riskService.listProfiles,
  });
}

export function useActiveRiskProfile() {
  return useQuery({
    queryKey: ["risk-profiles", "active"],
    queryFn: riskService.getActiveProfile,
  });
}

export function useRiskDecisions(filters = {}) {
  return useQuery({
    queryKey: ["risk-decisions", filters],
    queryFn: () => riskService.listDecisions(filters),
  });
}

export function useRiskProfileMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["risk-profiles"] });

  const create = useMutation({
    mutationFn: riskService.createProfile,
    onSuccess: invalidate,
  });

  const activate = useMutation({
    mutationFn: riskService.activateProfile,
    onSuccess: invalidate,
  });

  const deactivate = useMutation({
    mutationFn: riskService.deactivateProfile,
    onSuccess: invalidate,
  });

  return { create, activate, deactivate };
}
