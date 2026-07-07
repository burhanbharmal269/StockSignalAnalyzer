import apiClient from "@/lib/api-client";
import type {
  CapitalAllocation,
  CapitalAllocationListResponse,
  EffectiveAccountState,
  Portfolio,
  PortfolioListResponse,
} from "@/types";

export const capitalService = {
  listAllocations: () =>
    apiClient
      .get<CapitalAllocationListResponse>("capital-allocations")
      .then((r) => r.data.allocations),

  getActiveAllocation: () =>
    apiClient
      .get<CapitalAllocation>("capital-allocations/active")
      .then((r) => r.data),

  createAllocation: (data: Partial<CapitalAllocation>) =>
    apiClient
      .post<CapitalAllocation>("capital-allocations", data)
      .then((r) => r.data),

  activateAllocation: (id: string) =>
    apiClient
      .post<CapitalAllocation>(`capital-allocations/${id}/activate`)
      .then((r) => r.data),

  updateCapital: (id: string, amount: number) =>
    apiClient
      .patch<CapitalAllocation>(`capital-allocations/${id}/capital`, {
        new_capital: amount,
      })
      .then((r) => r.data),

  updateMode: (id: string, mode: string) =>
    apiClient
      .patch<CapitalAllocation>(`capital-allocations/${id}/mode`, {
        capital_source_mode: mode,
      })
      .then((r) => r.data),

  listPortfolios: () =>
    apiClient
      .get<PortfolioListResponse>("portfolios")
      .then((r) => r.data.portfolios),

  getActivePortfolio: () =>
    apiClient.get<Portfolio>("portfolios/active").then((r) => r.data),

  createPortfolio: (data: Partial<Portfolio>) =>
    apiClient.post<Portfolio>("portfolios", data).then((r) => r.data),

  activatePortfolio: (id: string) =>
    apiClient
      .post<Portfolio>(`portfolios/${id}/activate`)
      .then((r) => r.data),

  getEffectiveAccountState: () =>
    apiClient
      .get<EffectiveAccountState>("effective-account-state")
      .then((r) => r.data),
};
