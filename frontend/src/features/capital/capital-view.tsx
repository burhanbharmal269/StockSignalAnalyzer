"use client";

import { useCapitalAllocations, useActiveAllocation, useEffectiveAccountState, useCapitalMutations } from "@/hooks/use-capital-framework";
import { MetricTile } from "@/components/shared/metric-tile";
import { StatusIndicator } from "@/components/shared/status-indicator";
import { DataTable } from "@/components/shared/data-table";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import { toast } from "sonner";
import { DollarSign } from "lucide-react";
import type { CapitalAllocation } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";

const allocationColumns: ColumnDef<CapitalAllocation>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "allocation_type", header: "Type" },
  { accessorKey: "capital_source_mode", header: "Mode" },
  { accessorKey: "universe_scope", header: "Universe" },
  {
    accessorKey: "allocated_capital",
    header: "Allocated Capital",
    cell: ({ row }) => <span className="tabular-nums font-medium">{formatCurrency(row.original.allocated_capital)}</span>,
  },
  {
    accessorKey: "is_active",
    header: "Status",
    cell: ({ row }) => <StatusIndicator status={row.original.is_active ? "active" : "inactive"} size="sm" />,
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ row }) => <span className="text-xs text-muted-foreground">{formatDateTime(row.original.created_at)}</span>,
  },
];

export function CapitalView() {
  const { data: allocations, isLoading } = useCapitalAllocations();
  const { data: active } = useActiveAllocation();
  const { data: eas } = useEffectiveAccountState();
  const { activateAllocation } = useCapitalMutations();

  return (
    <div className="space-y-6">
      {/* EAS summary */}
      {eas && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricTile label="Effective Capital" value={formatCurrency(eas.effective_capital)} sub={`Mode: ${eas.capital_source_mode}`} icon={DollarSign} />
          <MetricTile label="Effective Margin" value={formatCurrency(eas.effective_margin)} icon={DollarSign} />
          <MetricTile label="Broker Capital" value={formatCurrency(eas.broker_capital)} sub="Live broker state" icon={DollarSign} />
          <MetricTile label="Configured Capital" value={formatCurrency(eas.configured_capital)} sub="From allocation" icon={DollarSign} />
        </div>
      )}

      {/* Active allocation detail */}
      {active && (
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium mb-3">Active Allocation — {active.name}</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
            <div><span className="text-muted-foreground">Mode:</span> <span className="font-medium">{active.capital_source_mode}</span></div>
            <div><span className="text-muted-foreground">Type:</span> <span className="font-medium">{active.allocation_type}</span></div>
            <div><span className="text-muted-foreground">Universe:</span> <span className="font-medium">{active.universe_scope}</span></div>
            <div><span className="text-muted-foreground">Capital:</span> <span className="font-medium">{formatCurrency(active.allocated_capital)}</span></div>
          </div>
          {eas && (
            <p className="text-xs text-muted-foreground mt-2">
              Captured at: {formatDateTime(eas.captured_at)}
            </p>
          )}
        </div>
      )}

      {/* All allocations */}
      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-3">Capital Allocations</h2>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <DataTable
            columns={[
              ...allocationColumns,
              {
                id: "actions",
                header: "",
                cell: ({ row }) => {
                  const a = row.original;
                  if (a.is_active) return null;
                  return (
                    <button
                      className="text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20"
                      onClick={() => activateAllocation.mutate(a.allocation_id, { onSuccess: () => toast.success("Allocation activated") })}
                    >
                      Activate
                    </button>
                  );
                },
              },
            ]}
            data={allocations ?? []}
            emptyMessage="No allocations"
          />
        )}
      </div>
    </div>
  );
}
