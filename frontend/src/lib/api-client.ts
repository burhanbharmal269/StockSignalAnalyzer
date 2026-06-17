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
