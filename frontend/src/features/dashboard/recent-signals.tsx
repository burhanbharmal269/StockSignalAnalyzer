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

function formatContract(signal: Signal): string | null {
  if (!signal.option_type || !signal.option_strike || !signal.option_expiry) return null;
  const d = new Date(signal.option_expiry);
  const day = d.getUTCDate();
  const month = d.toLocaleString("en-IN", { month: "short", timeZone: "UTC" });
  const strike =
    signal.option_strike % 1 === 0
      ? signal.option_strike.toFixed(0)
      : signal.option_strike.toFixed(1);
  return `${day} ${month} ${strike} ${signal.option_type}`;
}

const columns: ColumnDef<Signal>[] = [
  {
    accessorKey: "symbol",
    header: "Symbol",
    cell: ({ row }) => (
      <span className="font-mono font-semibold text-xs">{row.original.symbol}</span>
    ),
  },
  {
    accessorKey: "signal_type",
    header: "Dir",
    cell: ({ row }) => (
      <span className={cn("font-medium text-xs", DIRECTION_COLOR[row.original.signal_type] ?? "")}>
        {row.original.signal_type}
      </span>
    ),
  },
  {
    id: "contract",
    header: "Contract",
    cell: ({ row }) => {
      const label = formatContract(row.original);
      const type = row.original.option_type;
      if (!label) return <span className="text-muted-foreground text-xs">—</span>;
      return (
        <span className={cn("font-mono text-xs font-bold", type === "CE" ? "text-profit" : "text-loss")}>
          {label}
        </span>
      );
    },
  },
  {
    id: "option_entry",
    header: "Entry",
    cell: ({ row }) => {
      const v = row.original.option_entry;
      return (
        <span className="tabular-nums text-xs font-medium">
          {v != null ? `₹${v.toFixed(2)}` : "—"}
        </span>
      );
    },
  },
  {
    id: "grade",
    header: "Grade",
    cell: ({ row }) => {
      const score = row.original.adjusted_score;
      if (score == null) return <span className="text-muted-foreground text-xs">—</span>;
      const grade = score >= 65 ? "A" : "B";
      return (
        <span
          title={`Score: ${score.toFixed(1)}`}
          className={cn(
            "text-xs font-bold px-1 py-0.5 rounded",
            grade === "A"
              ? "bg-profit/10 text-profit border border-profit/30"
              : "bg-warning/10 text-warning border border-warning/30"
          )}
        >
          {grade}
        </span>
      );
    },
  },
  {
    accessorKey: "confidence",
    header: "Conf%",
    cell: ({ row }) => {
      const c = row.original.confidence;
      if (c == null) return <span className="text-muted-foreground text-xs">—</span>;
      const color = c >= 65 ? "text-profit" : c >= 50 ? "text-warning" : "text-muted-foreground";
      return <span className={cn("tabular-nums text-xs", color)}>{c.toFixed(0)}%</span>;
    },
  },
  {
    accessorKey: "state",
    header: "Status",
    cell: ({ row }) => (
      <span className={cn("text-xs font-medium", STATE_COLOR[row.original.state] ?? "")}>
        {row.original.state}
      </span>
    ),
  },
  {
    accessorKey: "created_at",
    header: "Age",
    cell: ({ row }) => (
      <span className="text-xs text-muted-foreground">{formatRelativeTime(row.original.created_at)}</span>
    ),
  },
];

export function RecentSignals() {
  useSignalLiveUpdates();
  const { data, isLoading, isError } = useSignals({ page_size: 10 });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (isError) return <p className="text-sm text-destructive">Failed to load signals</p>;

  return (
    <DataTable
      columns={columns}
      data={data?.signals ?? []}
      emptyMessage="No signals yet"
    />
  );
}
