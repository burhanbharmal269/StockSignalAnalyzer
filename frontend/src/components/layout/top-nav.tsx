"use client";

import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { LogOut, Wifi, WifiOff, User } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { useWSStatus } from "@/providers/websocket-provider";
import { KillSwitchButton } from "@/components/shared/kill-switch-button";
import { LiveDataBadge, ExecutionModeBadge } from "@/components/shared/trading-mode-badge";
import { executionService } from "@/services/execution.service";
import { cn } from "@/lib/utils";
import type { ExecutionMode } from "@/types";

const PAGE_TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/universe": "Universe",
  "/signals": "Signals",
  "/orders": "Orders",
  "/positions": "Positions",
  "/risk": "Risk Management",
  "/capital": "Capital Framework",
  "/portfolios": "Portfolios",
  "/broker": "Broker",
  "/analytics": "Analytics",
  "/system-health": "System Health",
  "/paper-trading": "Paper Trading",
  "/paper-daemon": "Paper Daemon",
  "/opportunities": "Opportunities",
  "/backtest": "Backtest",
  "/ai-insights": "AI Insights",
  "/option-chain": "Option Chain",
  "/settings": "Settings",
  "/signal-analytics": "Signal Analytics",
  "/strategy-analytics": "Strategy Analytics",
  "/filter-analytics": "Filter Analytics",
  "/signal-intelligence": "Signal Intelligence",
};

export function TopNav() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { isConnected } = useWSStatus();

  const { data: executionStatus } = useQuery({
    queryKey: ["execution-status"],
    queryFn: executionService.getStatus,
    refetchInterval: 30_000,
    staleTime: 20_000,
  });

  const executionMode = (executionStatus?.execution_mode ?? "MANUAL") as ExecutionMode;
  const ordersBlocked = executionStatus?.orders_blocked ?? true;

  const title =
    PAGE_TITLES[pathname] ??
    Object.entries(PAGE_TITLES).find(([k]) => pathname.startsWith(k))?.[1] ??
    "Dashboard";

  return (
    <header className="h-14 border-b flex items-center px-6 gap-4 shrink-0 bg-background">
      <h1 className="text-sm font-semibold flex-1">{title}</h1>

      <div className="flex items-center gap-3">
        {/* Always show LIVE DATA — market data is always live */}
        <LiveDataBadge />

        {/* Execution mode: MANUAL (gray) or AUTOMATIC (orange) */}
        <ExecutionModeBadge mode={executionMode} ordersBlocked={ordersBlocked} />

        {/* Execution lock toggle */}
        <KillSwitchButton />

        <div
          className={cn(
            "flex items-center gap-1.5 text-xs",
            isConnected ? "text-profit" : "text-muted-foreground"
          )}
          title={isConnected ? "WebSocket connected" : "WebSocket disconnected"}
        >
          {isConnected ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
          <span>{isConnected ? "Online" : "Offline"}</span>
        </div>

        <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <User className="h-4 w-4" />
          <span>{user?.username ?? "—"}</span>
        </div>

        <button
          onClick={() => logout()}
          className="text-muted-foreground hover:text-foreground transition-colors"
          title="Logout"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </header>
  );
}
