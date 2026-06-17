"use client";

import { useRiskProfiles, useActiveRiskProfile, useRiskProfileMutations, useRiskDecisions } from "@/hooks/use-risk";
import { StatusIndicator } from "@/components/shared/status-indicator";
import { DataTable } from "@/components/shared/data-table";
import { formatDateTime } from "@/lib/utils";
import { toast } from "sonner";
import type { RiskProfile, RiskDecision } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";

const profileColumns: ColumnDef<RiskProfile>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "profile_type", header: "Type" },
  {
    accessorKey: "is_active",
    header: "Status",
    cell: ({ row }) => (
      <StatusIndicator
        status={row.original.is_active ? "active" : "inactive"}
        size="sm"
      />
    ),
  },
  {
    accessorKey: "risk_per_trade_pct",
    header: "Risk/Trade %",
    cell: ({ row }) => `${row.original.risk_per_trade_pct}%`,
  },
  { accessorKey: "max_open_positions", header: "Max Positions" },
  {
    accessorKey: "daily_loss_pct",
    header: "Daily Loss %",
    cell: ({ row }) => `${row.original.daily_loss_pct}%`,
  },
  {
    accessorKey: "drawdown_pct",
    header: "Max Drawdown %",
    cell: ({ row }) => `${row.original.drawdown_pct}%`,
  },
];

const decisionColumns: ColumnDef<RiskDecision>[] = [
  {
    accessorKey: "signal_id",
    header: "Signal ID",
    cell: ({ row }) => (
      <span className="font-mono text-xs">{row.original.signal_id.slice(0, 8)}</span>
    ),
  },
  {
    accessorKey: "approved",
    header: "Decision",
    cell: ({ row }) => (
      <span
        className={
          row.original.approved ? "text-profit font-medium" : "text-loss font-medium"
        }
      >
        {row.original.approved ? "APPROVED" : "REJECTED"}
      </span>
    ),
  },
  {
    accessorKey: "rejection_reason",
    header: "Reason",
    cell: ({ row }) => (
      <span className="text-xs">{row.original.rejection_reason ?? "—"}</span>
    ),
  },
  {
    accessorKey: "position_size_lots",
    header: "Lots",
    cell: ({ row }) => (
      <span className="tabular-nums">{row.original.position_size_lots ?? "—"}</span>
    ),
  },
  {
    accessorKey: "evaluated_at",
    header: "Time",
    cell: ({ row }) => (
      <span className="text-xs text-muted-foreground">
        {formatDateTime(row.original.evaluated_at)}
      </span>
    ),
  },
];

export function RiskView() {
  const { data: profiles, isLoading: profilesLoading } = useRiskProfiles();
  const { data: active } = useActiveRiskProfile();
  const { data: decisions, isLoading: decisionsLoading } = useRiskDecisions({ page_size: 20 });
  const { activate, deactivate } = useRiskProfileMutations();

  return (
    <div className="space-y-6">
      {active && (
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium mb-3">Active Risk Profile</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">Name:</span>{" "}
              <span className="font-medium">{active.name}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Type:</span>{" "}
              <span className="font-medium">{active.profile_type}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Risk/Trade:</span>{" "}
              <span className="font-medium">{active.risk_per_trade_pct}%</span>
            </div>
            <div>
              <span className="text-muted-foreground">Max Positions:</span>{" "}
              <span className="font-medium">{active.max_open_positions}</span>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-3">Risk Profiles</h2>
        {profilesLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <DataTable
            columns={[
              ...profileColumns,
              {
                id: "actions",
                header: "",
                cell: ({ row }) => {
                  const p = row.original;
                  return p.is_active ? (
                    <button
                      className="text-xs px-2 py-1 rounded bg-muted hover:bg-muted/80"
                      onClick={() =>
                        deactivate.mutate(p.profile_id, {
                          onSuccess: () => toast.success("Profile deactivated"),
                        })
                      }
                    >
                      Deactivate
                    </button>
                  ) : (
                    <button
                      className="text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20"
                      onClick={() =>
                        activate.mutate(p.profile_id, {
                          onSuccess: () => toast.success("Profile activated"),
                        })
                      }
                    >
                      Activate
                    </button>
                  );
                },
              },
            ]}
            data={profiles ?? []}
            emptyMessage="No risk profiles"
          />
        )}
      </div>

      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-3">Recent Risk Decisions</h2>
        {decisionsLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <DataTable
            columns={decisionColumns}
            data={decisions?.items ?? []}
            emptyMessage="No decisions recorded"
          />
        )}
      </div>
    </div>
  );
}
