import apiClient from "@/lib/api-client";

export interface RiskCapitalSettings {
  total_capital: number;
  risk_per_trade_pct: number;
  daily_loss_pct: number;
  daily_loss_abs: number;
  weekly_loss_pct: number;
  weekly_loss_abs: number;
  max_open_positions: number;
  max_capital_per_underlying_pct: number;
  vix_threshold: number;
}

export const settingsService = {
  getRiskCapital: () =>
    apiClient
      .get<RiskCapitalSettings>("/settings/risk-capital")
      .then((r) => r.data),

  updateRiskCapital: (data: RiskCapitalSettings) =>
    apiClient
      .patch<RiskCapitalSettings>("/settings/risk-capital", data)
      .then((r) => r.data),
};
