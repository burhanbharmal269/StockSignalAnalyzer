"use client";

import { useQuery } from "@tanstack/react-query";
import { universeService } from "@/services/universe.service";
import { DataTable } from "@/components/shared/data-table";
import { StatusIndicator } from "@/components/shared/status-indicator";
import type { UniverseSymbol } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";

const columns: ColumnDef<UniverseSymbol>[] = [
  { accessorKey: "symbol", header: "Symbol", cell: ({ row }) => <span className="font-mono font-medium">{row.original.symbol}</span> },
  { accessorKey: "name", header: "Name" },
  { accessorKey: "sector", header: "Sector", cell: ({ row }) => <span className="text-muted-foreground">{row.original.sector ?? "—"}</span> },
  {
    accessorKey: "is_fo",
    header: "F&O",
    cell: ({ row }) => <StatusIndicator status={row.original.is_fo ? "active" : "inactive"} size="sm" />,
  },
  {
    accessorKey: "is_index",
    header: "Index",
    cell: ({ row }) => <span className="text-xs">{row.original.is_index ? "Yes" : "No"}</span>,
  },
];

export function UniverseView() {
  const { data, isLoading } = useQuery({
    queryKey: ["universe"],
    queryFn: universeService.list,
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">
          {data?.length ?? 0} symbols in universe
        </span>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <DataTable columns={columns} data={data ?? []} emptyMessage="No symbols in universe" />
      )}
    </div>
  );
}
