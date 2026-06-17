import apiClient from "@/lib/api-client";
import type { LoginRequest, LoginResponse, User } from "@/types";

export const authService = {
  login: (credentials: LoginRequest) =>
    apiClient.post<LoginResponse>("/auth/login", credentials).then((r) => r.data),

  logout: () => apiClient.post("/auth/logout"),

  refresh: (refreshToken: string) =>
    apiClient
      .post<LoginResponse>("/auth/refresh", { refresh_token: refreshToken })
      .then((r) => r.data),

  me: () => apiClient.get<User>("/auth/me").then((r) => r.data),

  changePassword: (oldPassword: string, newPassword: string) =>
    apiClient.post("/auth/change-password", { old_password: oldPassword, new_password: newPassword }),
};
