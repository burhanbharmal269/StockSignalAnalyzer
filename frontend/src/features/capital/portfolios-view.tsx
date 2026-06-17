"use client";

import { usePortfolios, useActivePortfolio, useCapitalMutations } from "@/hooks/use-capital-framework";
import { StatusIndicator } from "@/components/shared/status-indicator";
import { DataTable } from "@/components/shared/data-table";
import { formatDateTime, truncateId } from "@/lib/utils";
import { toast } from "sonner";
import type { Portfolio } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";

const columns: ColumnDef<Portfolio>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "portfolio_type", header: "Type" },
  {
    accessorKey: "risk_profile_id",
    header: "Risk Profile",
    cell: ({ row }) => row.original.risk_profile_id ? <span className="font-mono text-xs">{truncateId(row.original.risk_profile_id)}</span> : <span className="text-muted-foreground">—</span>,
  },
  {
    accessorKey: "allocation_id",
    header: "Allocation",
    cell: ({ row }) => row.original.allocation_id ? <span className="font-mono text-xs">{truncateId(row.original.allocation_id)}</span> : <span className="text-muted-foreground">—</span>,
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

export function PortfoliosView() {
  const { data: portfolios, isLoading } = usePortfolios();
  const { data: active } = useActivePortfolio();
  const { activatePortfolio } = useCapitalMutations();

  return (
    <div className="space-y-6">
      {active && (
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium mb-2">Active Portfolio</h2>
          <div className="flex gap-6 text-sm">
            <div><span className="text-muted-foreground">Name:</span> <span className="font-medium">{active.name}</span></div>
            <div><span className="text-muted-foreground">Type:</span> <span className="font-medium">{active.portfolio_type}</span></div>
          </div>
        </div>
      )}

      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-3">All Portfolios</h2>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <DataTable
            columns={[
              ...columns,
              {
                id: "actions",
                header: "",
                cell: ({ row }) => {
                  const p = row.original;
                  if (p.is_active) return null;
                  return (
                    <button
                      className="text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20"
                      onClick={() => activatePortfolio.mutate(p.portfolio_id, { onSuccess: () => toast.success("Portfolio activated") })}
                    >
                      Activate
                    </button>
                  );
                },
              },
            ]}
            data={portfolios ?? []}
            emptyMessage="No portfolios"
          />
        )}
      </div>
    </div>
  );
}
