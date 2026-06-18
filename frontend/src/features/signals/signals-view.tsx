"use client";

import { useState } from "react";
import { useSignals, useSignalMutations, useSignalLiveUpdates } from "@/hooks/use-signals";
import { DataTable } from "@/components/shared/data-table";
import { formatRelativeTime, cn } from "@/lib/utils";
import { toast } from "sonner";
import type { Signal } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";

const STATE_COLOR: Record<string, string> = {
  RISK_PENDING: "text-warning",
  RISK_APPROVED: "text-profit",
  RISK_REJECTED: "text-loss",
  EXECUTED: "text-primary",
  FORWARDED: "text-primary",
  EXPIRED: "text-muted-foreground",
  CANCELLED: "text-muted-foreground",
};

const MANUAL_ACTION_STATES = new Set(["RISK_PENDING"]);

function formatOptionChain(signal: Signal): string | null {
  if (!signal.option_type || !signal.option_strike || !signal.option_expiry) return null;
  const d = new Date(signal.option_expiry);
  const day = d.getUTCDate();
  const month = d.toLocaleString("en-IN", { month: "short", timeZone: "UTC" });
  const strike = Number.isInteger(signal.option_strike)
    ? signal.option_strike
    : signal.option_strike.toFixed(0);
  return `${day} ${month} ${strike} ${signal.option_type}`;
}

export function SignalsView() {
  useSignalLiveUpdates();
  const [stateFilter, setStateFilter] = useState<string>("");
  const [foOnly, setFoOnly] = useState(true);
  const { data, isLoading } = useSignals(stateFilter ? { state: stateFilter } : {});
  const { approve, reject } = useSignalMutations();

  const signals = foOnly
    ? (data?.signals ?? []).filter((s) => s.option_type != null)
    : (data?.signals ?? []);

  const columns: ColumnDef<Signal>[] = [
    {
      accessorKey: "symbol",
      header: "Stock",
      cell: ({ row }) => (
        <span className="font-mono font-semibold">{row.original.symbol}</span>
      ),
    },
    {
      id: "option_chain",
      header: "Contract",
      cell: ({ row }) => {
        const label = formatOptionChain(row.original);
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
        return <span className="tabular-nums text-sm font-medium">{v != null ? `₹${v.toFixed(2)}` : "—"}</span>;
      },
    },
    {
      id: "option_target",
      header: "Target",
      cell: ({ row }) => {
        const v = row.original.option_target;
        return <span className="tabular-nums text-sm font-medium text-profit">{v != null ? `₹${v.toFixed(2)}` : "—"}</span>;
      },
    },
    {
      id: "option_sl",
      header: "Stop Loss",
      cell: ({ row }) => {
        const v = row.original.option_sl;
        return <span className="tabular-nums text-sm font-medium text-loss">{v != null ? `₹${v.toFixed(2)}` : "—"}</span>;
      },
    },
    {
      accessorKey: "strategy_type",
      header: "Strategy",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">{row.original.strategy_type}</span>
      ),
    },
    {
      accessorKey: "regime",
      header: "Regime",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">{row.original.regime}</span>
      ),
    },
    {
      accessorKey: "state",
      header: "Status",
      cell: ({ row }) => {
        const s = row.original.state;
        return <span className={cn("text-xs font-medium", STATE_COLOR[s] ?? "")}>{s}</span>;
      },
    },
    {
      accessorKey: "created_at",
      header: "Age",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {formatRelativeTime(row.original.created_at)}
        </span>
      ),
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

  const withContractCount = (data?.signals ?? []).filter((s) => s.option_type != null).length;
  const totalCount = data?.signals?.length ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-medium text-muted-foreground">
          {foOnly ? withContractCount : totalCount} signals
          {foOnly && totalCount > withContractCount && (
            <span className="ml-2 text-xs text-muted-foreground/60">
              ({totalCount - withContractCount} without contract hidden)
            </span>
          )}
        </h2>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => setFoOnly((v) => !v)}
            className={cn(
              "text-xs px-3 py-1 rounded border font-medium",
              foOnly
                ? "bg-primary text-primary-foreground border-primary"
                : "border-border hover:bg-muted text-muted-foreground"
            )}
          >
            {foOnly ? "F&O Only" : "All Signals"}
          </button>
          <div className="w-px bg-border" />
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
          data={signals}
          emptyMessage={foOnly ? "No F&O signals with contracts yet" : "No signals"}
        />
      )}
    </div>
  );
}
