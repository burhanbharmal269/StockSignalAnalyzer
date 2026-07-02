// Defaults to same-origin so requests go through the reverse proxy (nginx) that
// routes /api and /ws to the backend on the same domain/port as the frontend —
// no hardcoded host or port. Only overridden when NEXT_PUBLIC_API_URL/WS_URL
// are explicitly set at build time (e.g. backend hosted on a different origin).
function _defaultApiBase(): string {
  if (typeof window === "undefined") return "http://localhost:8000";
  return window.location.origin;
}

function _defaultWsBase(): string {
  if (typeof window === "undefined") return "ws://localhost:8000";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? _defaultApiBase();
export const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL ?? _defaultWsBase();
export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? "SSA Trading Dashboard";

export const TOKEN_KEY = "ssa_access_token";
export const REFRESH_TOKEN_KEY = "ssa_refresh_token";

export const QUERY_STALE_TIME = 30_000; // 30s
export const QUERY_RETRY_COUNT = 1;

export const WS_RECONNECT_DELAY = 3_000;
export const WS_MAX_RECONNECT_ATTEMPTS = 10;

export const NAV_ITEMS = [
  { label: "Dashboard", href: "/dashboard", icon: "LayoutDashboard" },
  { label: "Universe", href: "/universe", icon: "Globe" },
  { label: "Signals", href: "/signals", icon: "Zap" },
  { label: "Orders", href: "/orders", icon: "ShoppingCart" },
  { label: "Positions", href: "/positions", icon: "TrendingUp" },
  { label: "Risk", href: "/risk", icon: "Shield" },
  { label: "Capital", href: "/capital", icon: "DollarSign" },
  { label: "Portfolios", href: "/portfolios", icon: "Briefcase" },
  { label: "Broker", href: "/broker", icon: "Server" },
  { label: "Analytics", href: "/analytics", icon: "BarChart2" },
  { label: "System Health", href: "/system-health", icon: "Activity" },
  { label: "Paper Trading", href: "/paper-trading", icon: "FileText" },
  { label: "Settings", href: "/settings", icon: "Settings" },
] as const;
