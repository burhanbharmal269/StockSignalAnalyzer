"use client";

import { useSignals, useSignalLiveUpdates } from "@/hooks/use-signals";
import { DataTable } from "@/components/shared/data-table";
import { formatRelativeTime } from "@/lib/utils";
import type { Signal } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";
import { cn } from "@/lib/utils";

const DIRECTION_COLOR: Record<string, string> = {
  LONG: "text-profit",
  SHORT: "text-loss",
  NEUTRAL: "text-muted-foreground",
};

const STATE_COLOR: Record<string, string> = {
  RISK_PENDING: "text-warning",
  RISK_APPROVED: "text-profit",
  RISK_REJECTED: "text-loss",
  EXECUTED: "text-primary",
  EXPIRED: "text-muted-foreground",
  CANCELLED: "text-muted-foreground",
  FORWARDED: "text-primary",
};

const columns: ColumnDef<Signal>[] = [
  { accessorKey: "symbol", header: "Symbol" },
  {
    accessorKey: "signal_type",
    header: "Dir",
    cell: ({ row }) => (
      <span className={cn("font-medium", DIRECTION_COLOR[row.original.signal_type] ?? "")}>
        {row.original.signal_type}
      </span>
    ),
  },
  {
    accessorKey: "confidence",
    header: "Confidence",
    cell: ({ row }) => {
      const c = row.original.confidence;
      return c != null ? `${(c * 100).toFixed(0)}%` : "—";
    },
  },
  {
    accessorKey: "state",
    header: "Status",
    cell: ({ row }) => (
      <span className={cn("text-sm", STATE_COLOR[row.original.state] ?? "")}>
        {row.original.state}
      </span>
    ),
  },
  {
    accessorKey: "created_at",
    header: "Age",
    cell: ({ row }) => formatRelativeTime(row.original.created_at),
  },
];

export function RecentSignals() {
  useSignalLiveUpdates();
  const { data, isLoading } = useSignals({ page_size: 10 });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <DataTable
      columns={columns}
      data={data?.signals ?? []}
      emptyMessage="No signals yet"
    />
  );
}
