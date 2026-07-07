// API calls go through Next.js rewrites (same origin) so they reach the backend
// regardless of which host/port the browser is on.
// WebSocket routing is protocol-dependent:
//   HTTPS (production) → nginx at same origin proxies /ws to backend (no port needed)
//   HTTP  (local dev)  → connect directly to the exposed backend port 8000
function _defaultApiBase(): string {
  if (typeof window === "undefined") return "http://localhost:8000";
  return window.location.origin;
}

function _defaultWsBase(): string {
  if (typeof window === "undefined") return "ws://localhost:8000";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  if (window.location.protocol === "https:") {
    // Reverse proxy handles TLS and routes /ws to the backend (see deploy/nginx.conf).
    return `${proto}//${window.location.hostname}`;
  }
  // Local dev: Next.js can't proxy WS upgrades, so connect directly to backend port.
  return `${proto}//${window.location.hostname}:8000`;
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
  { label: "Research Hub", href: "/research-hub", icon: "FlaskConical" },
  { label: "Strategy Versions", href: "/strategy-versions", icon: "GitBranch" },
  { label: "Param Optimization", href: "/parameter-optimization", icon: "Sliders" },
  { label: "Walk-Forward", href: "/walk-forward", icon: "LineChart" },
  { label: "Monte Carlo", href: "/monte-carlo", icon: "Shuffle" },
  { label: "Regime Performance", href: "/regime-performance", icon: "Map" },
  { label: "Symbol Rankings", href: "/symbol-rankings", icon: "Trophy" },
  { label: "False Positive", href: "/false-positive", icon: "AlertTriangle" },
  { label: "Promotion Queue", href: "/strategy-promotion", icon: "Rocket" },
] as const;
