export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_BASE_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
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
