"use client";

import { usePositions, usePositionMutations, usePositionLiveUpdates } from "@/hooks/use-positions";
import { DataTable } from "@/components/shared/data-table";
import { PnLDisplay } from "@/components/shared/pnl-display";
import { TradingModeBadge } from "@/components/shared/trading-mode-badge";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import { toast } from "sonner";
import type { Position } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";

const DIRECTION_COLOR: Record<string, string> = {
  LONG: "text-profit font-semibold",
  SHORT: "text-loss font-semibold",
  NEUTRAL: "text-muted-foreground",
};

export function PositionsView() {
  usePositionLiveUpdates();
  const { data, isLoading } = usePositions({ status: "OPEN" });
  const { close } = usePositionMutations();

  const columns: ColumnDef<Position>[] = [
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
    {
      accessorKey: "quantity",
      header: "Qty",
      cell: ({ row }) => <span className="tabular-nums">{row.original.quantity}</span>,
    },
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
    {
      accessorKey: "realized_pnl",
      header: "Realized PnL",
      cell: ({ row }) => <PnLDisplay value={row.original.realized_pnl} size="sm" />,
    },
    {
      accessorKey: "trading_mode",
      header: "Mode",
      cell: ({ row }) => (
        <TradingModeBadge mode={row.original.trading_mode as "LIVE" | "PAPER"} />
      ),
    },
    {
      accessorKey: "opened_at",
      header: "Opened",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {formatDateTime(row.original.opened_at)}
        </span>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const p = row.original;
        if (p.state === "CLOSED") return null;
        return (
          <button
            className="text-xs px-2 py-1 rounded bg-loss/10 text-loss hover:bg-loss/20"
            onClick={() =>
              close.mutate(
                { id: p.position_id, exit_price: p.current_price },
                { onSuccess: () => toast.success("Position closed") }
              )
            }
          >
            Close
          </button>
        );
      },
    },
  ];

  const totalUnrealized =
    (data?.positions ?? []).reduce((s, p) => s + p.unrealized_pnl, 0);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">
          {data?.total ?? 0} open positions
        </span>
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Total Unrealized:</span>
          <PnLDisplay value={totalUnrealized} size="md" />
        </div>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <DataTable
          columns={columns}
          data={data?.positions ?? []}
          emptyMessage="No open positions"
        />
      )}
    </div>
  );
}
