import apiClient from "@/lib/api-client";

export const marketService = {
  getUniverse: (params: { segment?: string; fo_only?: boolean } = {}) =>
    apiClient.get("market/universe", { params }).then((r) => r.data),

  getCandles: (symbol: string, timeframe = "15m", limit = 100) =>
    apiClient
      .get(`market/candles/${symbol}`, { params: { timeframe, limit } })
      .then((r) => r.data),

  getLtp: (symbols: string[]) =>
    apiClient
      .get("market/ltp", { params: { symbols: symbols.join(",") } })
      .then((r) => r.data),

  getBreadth: () => apiClient.get("market/breadth").then((r) => r.data),

  getBreadthHistory: (limit = 30) =>
    apiClient
      .get("market/breadth/history", { params: { limit } })
      .then((r) => r.data),

  triggerFetch: (symbol: string, timeframe = "D", days = 365) =>
    apiClient
      .post("market/fetch", null, { params: { symbol, timeframe, days } })
      .then((r) => r.data),
};

export const optionService = {
  getChain: (underlying: string) =>
    apiClient.get(`options/${underlying}`).then((r) => r.data),

  getPcrHistory: (underlying: string, limit = 20) =>
    apiClient
      .get(`options/${underlying}/history`, { params: { limit } })
      .then((r) => r.data),

  refresh: (underlying: string) =>
    apiClient.post(`options/${underlying}/refresh`).then((r) => r.data),
};

export const newsService = {
  getNews: (params: { limit?: number; symbol?: string } = {}) =>
    apiClient.get("news", { params }).then((r) => r.data),

  getMarketSentiment: () =>
    apiClient.get("news/sentiment/market").then((r) => r.data),

  getSymbolSentiment: (symbol: string, hours = 24) =>
    apiClient
      .get(`news/sentiment/${symbol}`, { params: { hours } })
      .then((r) => r.data),

  refresh: () => apiClient.post("news/refresh").then((r) => r.data),
};

export const opportunitiesService = {
  getOpportunities: (params: { limit?: number; direction?: string; type?: string } = {}) =>
    apiClient.get("opportunities", { params }).then((r) => r.data),

  runScan: (timeframe = "15m") =>
    apiClient
      .post("opportunities/scan", null, { params: { timeframe } })
      .then((r) => r.data),
};

export const backtestService = {
  runBacktest: (payload: {
    strategy: string;
    symbol: string;
    timeframe?: string;
    from_dt: string;
    to_dt: string;
    initial_capital?: number;
    risk_per_trade_pct?: number;
    params?: Record<string, unknown>;
  }) => apiClient.post("backtest/run", payload).then((r) => r.data),

  listRuns: (limit = 20) =>
    apiClient.get("backtest/runs", { params: { limit } }).then((r) => r.data),

  getTrades: (runId: string) =>
    apiClient.get(`backtest/runs/${runId}/trades`).then((r) => r.data),
};

export const aiService = {
  getMarketInsight: () => apiClient.get("ai/market").then((r) => r.data),

  getInsightHistory: (limit = 7) =>
    apiClient.get("ai/market/history", { params: { limit } }).then((r) => r.data),

  generateInsight: () =>
    apiClient.post("ai/market/generate").then((r) => r.data),

  getStrategyRecommendation: (
    symbol: string,
    regime = "UNKNOWN",
    timeframe = "15m",
    isIndex = false
  ) =>
    apiClient
      .get(`ai/strategy/${symbol}`, { params: { regime, timeframe, is_index: isIndex } })
      .then((r) => r.data),
};

export const paperDaemonService = {
  getStatus: () => apiClient.get("paper/status").then((r) => r.data),
  start: () => apiClient.post("paper/start").then((r) => r.data),
  stop: () => apiClient.post("paper/stop").then((r) => r.data),
  getJournal: (limit = 50) =>
    apiClient.get("paper/journal", { params: { limit } }).then((r) => r.data),
  getPerformance: () => apiClient.get("paper/performance").then((r) => r.data),
};
