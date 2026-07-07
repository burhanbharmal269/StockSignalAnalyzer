import apiClient from "@/lib/api-client";
import type { ExecutionLockState, ExecutionMode } from "@/types";

export const executionService = {
  getStatus: () =>
    apiClient.get<ExecutionLockState>("execution/status").then((r) => r.data),

  lock: (note = "") =>
    apiClient
      .post<ExecutionLockState & { action: string }>("execution/lock", { note })
      .then((r) => r.data),

  unlock: (note = "") =>
    apiClient
      .post<ExecutionLockState & { action: string }>("execution/unlock", { note })
      .then((r) => r.data),

  setMode: (mode: ExecutionMode, note = "") =>
    apiClient
      .post<ExecutionLockState & { action: string }>("execution/mode", { mode, note })
      .then((r) => r.data),
};
