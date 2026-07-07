import apiClient from "@/lib/api-client";
import type {
  BrokerLoginUrl,
  BrokerSessionResponse,
  BrokerStatus,
  KillSwitchState,
  TradingMode,
  TradingModeResponse,
} from "@/types";

export const brokerService = {
  getStatus: () =>
    apiClient.get<BrokerStatus>("broker/status").then((r) => r.data),

  getMode: () =>
    apiClient.get<TradingModeResponse>("broker/mode").then((r) => r.data),

  getSession: () =>
    apiClient.get<BrokerSessionResponse>("broker/session").then((r) => r.data),

  setMode: (mode: TradingMode, reason: string) =>
    apiClient
      .post<TradingModeResponse>("broker/mode", { mode, reason })
      .then((r) => r.data),

  getLoginUrl: () =>
    apiClient.get<BrokerLoginUrl>("broker/login").then((r) => r.data),

  submitCallback: (request_token: string) =>
    apiClient
      .post<BrokerSessionResponse>("broker/callback", { request_token })
      .then((r) => r.data),

  activateKillSwitch: (reason: string) =>
    apiClient
      .post<KillSwitchState>("broker/kill-switch/activate", { reason })
      .then((r) => r.data),

  deactivateKillSwitch: (note: string, override_loss_check = false) =>
    apiClient
      .post<KillSwitchState>("broker/kill-switch/deactivate", {
        note,
        override_loss_check,
      })
      .then((r) => r.data),
};
