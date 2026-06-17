"use client";

import { useState } from "react";
import { useSignals, useSignalMutations, useSignalLiveUpdates } from "@/hooks/use-signals";
import { DataTable } from "@/components/shared/data-table";
import { formatRelativeTime, cn } from "@/lib/utils";
import { toast } from "sonner";
import type { Signal } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";

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
  FORWARDED: "text-primary",
  EXPIRED: "text-muted-foreground",
  CANCELLED: "text-muted-foreground",
};

// Only RISK_PENDING signals can be manually approved/rejected (backend enforces this)
const MANUAL_ACTION_STATES = new Set(["RISK_PENDING"]);

export function SignalsView() {
  useSignalLiveUpdates();
  const [stateFilter, setStateFilter] = useState<string>("");
  const { data, isLoading } = useSignals(stateFilter ? { state: stateFilter } : {});
  const { approve, reject } = useSignalMutations();

  const columns: ColumnDef<Signal>[] = [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <span className="font-mono font-medium">{row.original.symbol}</span>
      ),
    },
    {
      accessorKey: "signal_type",
      header: "Direction",
      cell: ({ row }) => (
        <span className={cn("font-semibold", DIRECTION_COLOR[row.original.signal_type] ?? "")}>
          {row.original.signal_type}
        </span>
      ),
    },
    {
      accessorKey: "adjusted_score",
      header: "Score",
      cell: ({ row }) => {
        const s = row.original.adjusted_score;
        return <span className="tabular-nums">{s != null ? s.toFixed(1) : "—"}</span>;
      },
    },
    {
      accessorKey: "confidence",
      header: "Confidence",
      cell: ({ row }) => {
        const c = row.original.confidence;
        // Backend sends confidence as 0-100 (not 0-1)
        return <span className="tabular-nums">{c != null ? `${c.toFixed(0)}%` : "—"}</span>;
      },
    },
    {
      accessorKey: "entry_price",
      header: "Entry",
      cell: ({ row }) => {
        const v = row.original.entry_price;
        return <span className="tabular-nums">{v != null ? `₹${v.toFixed(2)}` : "—"}</span>;
      },
    },
    {
      accessorKey: "stop_loss_price",
      header: "SL",
      cell: ({ row }) => {
        const v = row.original.stop_loss_price;
        return <span className="tabular-nums text-loss">{v != null ? `₹${v.toFixed(2)}` : "—"}</span>;
      },
    },
    {
      accessorKey: "target_price",
      header: "Target",
      cell: ({ row }) => {
        const v = row.original.target_price;
        return <span className="tabular-nums text-profit">{v != null ? `₹${v.toFixed(2)}` : "—"}</span>;
      },
    },
    {
      accessorKey: "strategy_type",
      header: "Strategy",
    },
    {
      accessorKey: "regime",
      header: "Regime",
    },
    {
      accessorKey: "state",
      header: "Status",
      cell: ({ row }) => {
        const s = row.original.state;
        return <span className={STATE_COLOR[s] ?? ""}>{s}</span>;
      },
    },
    {
      accessorKey: "created_at",
      header: "Age",
      cell: ({ row }) => formatRelativeTime(row.original.created_at),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const sig = row.original;
        if (!MANUAL_ACTION_STATES.has(sig.state)) return null;
        return (
          <div className="flex gap-1">
            <button
              className="text-xs px-2 py-1 rounded bg-profit/10 text-profit hover:bg-profit/20"
              onClick={() =>
                approve.mutate(sig.signal_id, {
                  onSuccess: () => toast.success("Signal approved"),
                })
              }
            >
              Approve
            </button>
            <button
              className="text-xs px-2 py-1 rounded bg-loss/10 text-loss hover:bg-loss/20"
              onClick={() =>
                reject.mutate(
                  { id: sig.signal_id, reason: "Manual reject" },
                  { onSuccess: () => toast.success("Signal rejected") }
                )
              }
            >
              Reject
            </button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted-foreground">
          {data?.total ?? 0} signals
        </h2>
        <div className="flex gap-2">
          {(["RISK_PENDING", "RISK_APPROVED", "RISK_REJECTED", "EXECUTED"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setStateFilter((f) => (f === s ? "" : s))}
              className={cn(
                "text-xs px-2 py-1 rounded border",
                stateFilter === s
                  ? "bg-primary text-primary-foreground border-primary"
                  : "border-border hover:bg-muted"
              )}
            >
              {s.replace("RISK_", "")}
            </button>
          ))}
        </div>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <DataTable
          columns={columns}
          data={data?.signals ?? []}
          emptyMessage="No signals"
        />
      )}
    </div>
  );
}
