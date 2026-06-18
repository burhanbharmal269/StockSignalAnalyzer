"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { settingsService, type RiskCapitalSettings } from "@/services/settings.service";

export function useRiskCapitalSettings() {
  return useQuery({
    queryKey: ["settings", "risk-capital"],
    queryFn: settingsService.getRiskCapital,
  });
}

export function useUpdateRiskCapital() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: RiskCapitalSettings) => settingsService.updateRiskCapital(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["settings", "risk-capital"] }),
  });
}
