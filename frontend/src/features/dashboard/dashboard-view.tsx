"use client";

import { useQuery } from "@tanstack/react-query";
import { brokerService } from "@/services/broker.service";
import { MetricTile } from "@/components/shared/metric-tile";
import { StatusIndicator } from "@/components/shared/status-indicator";
import { PnLDisplay } from "@/components/shared/pnl-display";
import { TradingModeBadge } from "@/components/shared/trading-mode-badge";
import { useEffectiveAccountState } from "@/hooks/use-capital-framework";
import { usePositions } from "@/hooks/use-positions";
import { useSignals } from "@/hooks/use-signals";
import { useWSStatus } from "@/providers/websocket-provider";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import { DollarSign, TrendingUp, Zap } from "lucide-react";
import { PnLChart } from "./pnl-chart";
import { RecentSignals } from "./recent-signals";

export function DashboardView() {
  const { data: brokerStatus } = useQuery({
    queryKey: ["broker-status"],
    queryFn: brokerService.getStatus,
    refetchInterval: 15_000,
  });

  const { data: brokerMode } = useQuery({
    queryKey: ["broker-mode"],
    queryFn: brokerService.getMode,
    refetchInterval: 30_000,
  });

  const { isConnected } = useWSStatus();

  const { data: eas } = useEffectiveAccountState();
  const { data: positions } = usePositions({ state: "OPEN" });
  const { data: signals } = useSignals({ state: "RISK_PENDING" });

  const totalUnrealizedPnL =
    (positions?.positions ?? []).reduce((sum, p) => sum + p.unrealized_pnl, 0);

  return (
    <div className="space-y-6">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {brokerMode && (
            <TradingModeBadge mode={brokerMode.mode as "LIVE" | "PAPER"} />
          )}
          <StatusIndicator
            status={isConnected ? "healthy" : "unhealthy"}
            label={isConnected ? "System Online" : "System Offline"}
            size="sm"
          />
        </div>
        {brokerStatus && (
          <span className="text-xs text-muted-foreground">
            Last updated: {formatDateTime(brokerStatus.checked_at)}
          </span>
        )}
      </div>

      {/* Metric tiles */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricTile
          label="Effective Capital"
          value={eas ? formatCurrency(eas.effective_capital) : "—"}
          sub={eas ? `Mode: ${eas.capital_source_mode}` : undefined}
          icon={DollarSign}
        />
        <MetricTile
          label="Available Margin"
          value={eas ? formatCurrency(eas.effective_margin) : "—"}
          sub={eas ? `Daily limit: ${formatCurrency(eas.effective_daily_loss_limit)}` : undefined}
          icon={DollarSign}
        />
        <MetricTile
          label="Open Positions"
          value={positions?.total ?? "—"}
          sub="Unrealized PnL"
          icon={TrendingUp}
          trend={totalUnrealizedPnL >= 0 ? "up" : "down"}
        />
        <MetricTile
          label="Pending Signals"
          value={signals?.total ?? "—"}
          sub="Awaiting risk approval"
          icon={Zap}
        />
      </div>

      {/* PnL chart + unrealized */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium mb-4">Daily PnL (30d)</h2>
          <PnLChart />
        </div>
        <div className="rounded-lg border bg-card p-4 space-y-3">
          <h2 className="text-sm font-medium">Unrealized PnL</h2>
          <PnLDisplay value={totalUnrealizedPnL} size="lg" />
          {eas && (
            <div className="pt-2 space-y-1 text-xs text-muted-foreground">
              <div className="flex justify-between">
                <span>Daily loss limit</span>
                <span>{formatCurrency(eas.effective_daily_loss_limit)}</span>
              </div>
              <div className="flex justify-between">
                <span>Weekly loss limit</span>
                <span>{formatCurrency(eas.effective_weekly_loss_limit)}</span>
              </div>
              <div className="flex justify-between">
                <span>Risk per trade</span>
                <span>{eas.effective_risk_per_trade}%</span>
              </div>
              <div className="flex justify-between">
                <span>Max open positions</span>
                <span>{eas.effective_max_open_positions}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Recent signals */}
      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-4">Recent Signals</h2>
        <RecentSignals />
      </div>
    </div>
  );
}
