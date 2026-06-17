import Cookies from "js-cookie";
import { TOKEN_KEY, REFRESH_TOKEN_KEY } from "./constants";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return Cookies.get(REFRESH_TOKEN_KEY) ?? null;
}

export function setTokens(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken);
  Cookies.set(REFRESH_TOKEN_KEY, refreshToken, {
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    expires: 7,
  });
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY);
  Cookies.remove(REFRESH_TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}
