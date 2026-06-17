import axios, { AxiosError, type AxiosInstance } from "axios";
import { API_BASE_URL, TOKEN_KEY, REFRESH_TOKEN_KEY } from "./constants";
import Cookies from "js-cookie";

const apiClient: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
});

apiClient.interceptors.request.use((config) => {
  const token =
    typeof window !== "undefined" ? localStorage.getItem(TOKEN_KEY) : null;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: string) => void;
  reject: (reason: unknown) => void;
}> = [];

function processQueue(error: unknown, token: string | null = null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve(token!);
  });
  failedQueue = [];
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as typeof error.config & {
      _retry?: boolean;
    };

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers!.Authorization = `Bearer ${token}`;
          return apiClient(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = Cookies.get(REFRESH_TOKEN_KEY);
      if (!refreshToken) {
        processQueue(error);
        isRefreshing = false;
        clearAuthAndRedirect();
        return Promise.reject(error);
      }

      try {
        const { data } = await axios.post(
          `${API_BASE_URL}/api/v1/auth/refresh`,
          { refresh_token: refreshToken }
        );
        localStorage.setItem(TOKEN_KEY, data.access_token);
        processQueue(null, data.access_token);
        originalRequest.headers!.Authorization = `Bearer ${data.access_token}`;
        return apiClient(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError);
        clearAuthAndRedirect();
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

function clearAuthAndRedirect() {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
    Cookies.remove(REFRESH_TOKEN_KEY);
    window.location.href = "/login";
  }
}

export default apiClient;

/**
 * Extract a human-readable message from any thrown value.
 * Handles: AxiosError with FastAPI detail (string or array), plain Error, unknown.
 */
export function extractErrorMessage(err: unknown, fallback = "An unexpected error occurred"): string {
  if (!err) return fallback;

  // Axios error with a response body
  const axiosErr = err as { response?: { data?: unknown; status?: number }; message?: string };
  if (axiosErr.response) {
    const data = axiosErr.response.data as
      | { detail?: unknown; message?: string }
      | null
      | undefined;

    if (data) {
      const detail = data.detail;
      if (typeof detail === "string" && detail.length > 0) return detail;
      // FastAPI 422: detail is an array of validation error objects
      if (Array.isArray(detail) && detail.length > 0) {
        const first = detail[0] as { msg?: string; message?: string };
        return first.msg ?? first.message ?? "Validation error";
      }
      if (typeof data.message === "string" && data.message.length > 0) return data.message;
    }
    // Fallback to HTTP status text
    const status = axiosErr.response.status;
    if (status === 401) return "Unauthorized — please log in again";
    if (status === 403) return "Forbidden";
    if (status === 404) return "Not found";
    if (status === 502) return "Broker API error — check Kite credentials";
    if (status === 503) return "Service unavailable — KITE_API_KEY not configured";
    if (status) return `Server error (${status})`;
  }

  // Network error (no response)
  if (axiosErr.message) return axiosErr.message;

  // Plain Error
  if (err instanceof Error) return err.message;

  return fallback;
}
