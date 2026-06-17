"use client";

import { useQuery } from "@tanstack/react-query";
import { analyticsService } from "@/services/analytics.service";
import { MetricTile } from "@/components/shared/metric-tile";
import { DataTable } from "@/components/shared/data-table";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import { TrendingUp, Activity } from "lucide-react";
import type { ExecutionRecord } from "@/services/analytics.service";
import type { ColumnDef } from "@tanstack/react-table";

const recordColumns: ColumnDef<ExecutionRecord>[] = [
  { accessorKey: "symbol", header: "Symbol" },
  { accessorKey: "broker_name", header: "Broker" },
  { accessorKey: "trading_mode", header: "Mode" },
  {
    accessorKey: "realized_pnl",
    header: "PnL",
    cell: ({ row }) => {
      const v = row.original.realized_pnl;
      if (v == null) return <span className="text-muted-foreground">—</span>;
      return (
        <span className={v >= 0 ? "text-profit tabular-nums" : "text-loss tabular-nums"}>
          {formatCurrency(v)}
        </span>
      );
    },
  },
  {
    accessorKey: "total_e2e_latency_ms",
    header: "E2E Latency",
    cell: ({ row }) => {
      const v = row.original.total_e2e_latency_ms;
      return <span className="tabular-nums">{v != null ? `${v.toFixed(1)}ms` : "—"}</span>;
    },
  },
  {
    accessorKey: "slippage_bps",
    header: "Slippage (bps)",
    cell: ({ row }) => {
      const v = row.original.slippage_bps;
      return <span className="tabular-nums">{v != null ? v.toFixed(1) : "—"}</span>;
    },
  },
  {
    accessorKey: "recorded_at",
    header: "Time",
    cell: ({ row }) => (
      <span className="text-xs text-muted-foreground">
        {formatDateTime(row.original.recorded_at)}
      </span>
    ),
  },
];

export function AnalyticsView() {
  const { data: summary } = useQuery({
    queryKey: ["analytics", "execution-summary"],
    queryFn: () => analyticsService.getExecutionSummary(),
    refetchInterval: 60_000,
  });

  const { data: records, isLoading } = useQuery({
    queryKey: ["analytics", "execution-records"],
    queryFn: () => analyticsService.listExecutionRecords({ limit: 50 }),
  });

  const totalTrades = (summary?.win_count ?? 0) + (summary?.loss_count ?? 0);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricTile
          label="Total PnL"
          value={summary?.total_pnl != null ? formatCurrency(summary.total_pnl) : "—"}
          trend={summary?.total_pnl != null && summary.total_pnl >= 0 ? "up" : "down"}
          icon={TrendingUp}
        />
        <MetricTile
          label="Win Rate"
          value={summary ? `${(summary.win_rate * 100).toFixed(1)}%` : "—"}
          sub={summary ? `${totalTrades} trades` : undefined}
          icon={Activity}
        />
        <MetricTile
          label="Avg E2E Latency"
          value={
            summary?.avg_e2e_latency_ms != null
              ? `${summary.avg_e2e_latency_ms.toFixed(1)}ms`
              : "—"
          }
        />
        <MetricTile
          label="Avg Slippage"
          value={
            summary?.avg_slippage_bps != null
              ? `${summary.avg_slippage_bps.toFixed(1)} bps`
              : "—"
          }
        />
      </div>

      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-4">Execution Records</h2>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <DataTable
            columns={recordColumns}
            data={records?.records ?? []}
            emptyMessage="No execution records yet"
          />
        )}
      </div>
    </div>
  );
}
