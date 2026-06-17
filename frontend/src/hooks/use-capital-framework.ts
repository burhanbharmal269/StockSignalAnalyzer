"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { capitalService } from "@/services/capital.service";

export function useCapitalAllocations() {
  return useQuery({
    queryKey: ["capital-allocations"],
    queryFn: capitalService.listAllocations,
  });
}

export function useActiveAllocation() {
  return useQuery({
    queryKey: ["capital-allocations", "active"],
    queryFn: capitalService.getActiveAllocation,
  });
}

export function usePortfolios() {
  return useQuery({
    queryKey: ["portfolios"],
    queryFn: capitalService.listPortfolios,
  });
}

export function useActivePortfolio() {
  return useQuery({
    queryKey: ["portfolios", "active"],
    queryFn: capitalService.getActivePortfolio,
  });
}

export function useEffectiveAccountState() {
  return useQuery({
    queryKey: ["effective-account-state"],
    queryFn: capitalService.getEffectiveAccountState,
    refetchInterval: 30_000,
  });
}

export function useCapitalMutations() {
  const qc = useQueryClient();

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["capital-allocations"] });
    qc.invalidateQueries({ queryKey: ["effective-account-state"] });
  };

  const createAllocation = useMutation({
    mutationFn: capitalService.createAllocation,
    onSuccess: invalidateAll,
  });

  const activateAllocation = useMutation({
    mutationFn: capitalService.activateAllocation,
    onSuccess: invalidateAll,
  });

  const updateCapital = useMutation({
    mutationFn: ({ id, amount }: { id: string; amount: number }) =>
      capitalService.updateCapital(id, amount),
    onSuccess: invalidateAll,
  });

  const updateMode = useMutation({
    mutationFn: ({ id, mode }: { id: string; mode: string }) =>
      capitalService.updateMode(id, mode),
    onSuccess: invalidateAll,
  });

  const createPortfolio = useMutation({
    mutationFn: capitalService.createPortfolio,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolios"] }),
  });

  const activatePortfolio = useMutation({
    mutationFn: capitalService.activatePortfolio,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["portfolios"] }),
  });

  return { createAllocation, activateAllocation, updateCapital, updateMode, createPortfolio, activatePortfolio };
}
