import apiClient from "@/lib/api-client";
import type { UniverseSymbol, RegimeData } from "@/types";

export const universeService = {
  list: () =>
    apiClient
      .get<{ symbols: UniverseSymbol[] }>("market/universe")
      .then((r) => r.data.symbols),

  getRegime: (token: string, timeframe: string) =>
    apiClient
      .get<RegimeData>(`regime/${token}/${timeframe}/latest`)
      .then((r) => r.data),
};
