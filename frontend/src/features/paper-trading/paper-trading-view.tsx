"use client";

import { useOrders } from "@/hooks/use-orders";
import { usePositions } from "@/hooks/use-positions";
import { useSignals } from "@/hooks/use-signals";
import { DataTable } from "@/components/shared/data-table";
import { PnLDisplay } from "@/components/shared/pnl-display";
import { MetricTile } from "@/components/shared/metric-tile";
import { formatCurrency } from "@/lib/utils";
import type { Position } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";
import { TrendingUp } from "lucide-react";

const DIRECTION_COLOR: Record<string, string> = {
  LONG: "text-profit",
  SHORT: "text-loss",
  NEUTRAL: "text-muted-foreground",
};

const positionColumns: ColumnDef<Position>[] = [
  {
    accessorKey: "symbol",
    header: "Symbol",
    cell: ({ row }) => (
      <span className="font-mono font-medium">{row.original.symbol}</span>
    ),
  },
  {
    accessorKey: "direction",
    header: "Side",
    cell: ({ row }) => (
      <span className={DIRECTION_COLOR[row.original.direction] ?? ""}>
        {row.original.direction}
      </span>
    ),
  },
  { accessorKey: "quantity", header: "Qty" },
  {
    accessorKey: "entry_price",
    header: "Entry",
    cell: ({ row }) => (
      <span className="tabular-nums">{formatCurrency(row.original.entry_price)}</span>
    ),
  },
  {
    accessorKey: "current_price",
    header: "LTP",
    cell: ({ row }) => (
      <span className="tabular-nums">{formatCurrency(row.original.current_price)}</span>
    ),
  },
  {
    accessorKey: "unrealized_pnl",
    header: "Unrealized PnL",
    cell: ({ row }) => <PnLDisplay value={row.original.unrealized_pnl} size="sm" />,
  },
];

export function PaperTradingView() {
  const { data: positions, isLoading: posLoading } = usePositions({
    trading_mode: "PAPER",
  });
  const { data: orders } = useOrders({ trading_mode: "PAPER" });
  const { data: signals } = useSignals({});

  const totalUnrealized =
    (positions?.positions ?? []).reduce((s, p) => s + p.unrealized_pnl, 0);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricTile label="Paper Positions" value={positions?.total ?? 0} icon={TrendingUp} />
        <MetricTile label="Paper Orders" value={orders?.total ?? 0} />
        <MetricTile label="Active Signals" value={signals?.total ?? 0} />
        <div className="rounded-lg border bg-card p-4">
          <span className="text-xs text-muted-foreground uppercase tracking-wide">
            Unrealized PnL
          </span>
          <div className="mt-2">
            <PnLDisplay value={totalUnrealized} size="lg" />
          </div>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-4">
        <h2 className="text-sm font-medium mb-3">Open Paper Positions</h2>
        {posLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : (
          <DataTable
            columns={positionColumns}
            data={positions?.positions ?? []}
            emptyMessage="No open paper positions"
          />
        )}
      </div>
    </div>
  );
}
