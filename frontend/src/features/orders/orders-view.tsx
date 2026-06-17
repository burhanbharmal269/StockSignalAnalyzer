"use client";

import { useState } from "react";
import { useOrders, useOrderMutations, useOrderLiveUpdates } from "@/hooks/use-orders";
import { DataTable } from "@/components/shared/data-table";
import { TradingModeBadge } from "@/components/shared/trading-mode-badge";
import { formatCurrency, formatDateTime, cn, truncateId } from "@/lib/utils";
import { toast } from "sonner";
import type { Order } from "@/types";
import type { ColumnDef } from "@tanstack/react-table";

const STATE_COLOR: Record<string, string> = {
  PENDING: "text-warning",
  SUBMITTING: "text-warning",
  SUBMITTED: "text-primary",
  OPEN: "text-primary",
  PARTIALLY_FILLED: "text-primary",
  FILLED: "text-profit",
  CANCELLED: "text-muted-foreground",
  REJECTED: "text-loss",
  REJECTED_PRE_SUBMIT: "text-loss",
  EXPIRED: "text-muted-foreground",
};

const CANCELLABLE_STATES = new Set(["PENDING", "SUBMITTED", "OPEN"]);

export function OrdersView() {
  useOrderLiveUpdates();
  const [stateFilter, setStateFilter] = useState<string>("");
  const { data, isLoading } = useOrders(stateFilter ? { state: stateFilter } : {});
  const { cancel } = useOrderMutations();

  const columns: ColumnDef<Order>[] = [
    {
      accessorKey: "order_id",
      header: "ID",
      cell: ({ row }) => (
        <span className="font-mono text-xs">{truncateId(row.original.order_id)}</span>
      ),
    },
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <span className="font-mono font-medium">{row.original.symbol}</span>
      ),
    },
    {
      accessorKey: "transaction_type",
      header: "Side",
      cell: ({ row }) => (
        <span
          className={
            row.original.transaction_type === "BUY"
              ? "text-profit font-semibold"
              : "text-loss font-semibold"
          }
        >
          {row.original.transaction_type}
        </span>
      ),
    },
    { accessorKey: "order_type", header: "Type" },
    {
      accessorKey: "quantity",
      header: "Qty",
      cell: ({ row }) => (
        <span className="tabular-nums">{row.original.quantity}</span>
      ),
    },
    {
      accessorKey: "limit_price",
      header: "Price",
      cell: ({ row }) => (
        <span className="tabular-nums">
          {row.original.limit_price ? formatCurrency(row.original.limit_price) : "MKT"}
        </span>
      ),
    },
    {
      accessorKey: "average_fill_price",
      header: "Avg Price",
      cell: ({ row }) => (
        <span className="tabular-nums">
          {row.original.average_fill_price
            ? formatCurrency(row.original.average_fill_price)
            : "—"}
        </span>
      ),
    },
    {
      accessorKey: "filled_quantity",
      header: "Filled",
      cell: ({ row }) => (
        <span className="tabular-nums">{row.original.filled_quantity}</span>
      ),
    },
    {
      accessorKey: "state",
      header: "Status",
      cell: ({ row }) => (
        <span className={STATE_COLOR[row.original.state] ?? ""}>{row.original.state}</span>
      ),
    },
    {
      accessorKey: "trading_mode",
      header: "Mode",
      cell: ({ row }) => (
        <TradingModeBadge mode={row.original.trading_mode as "LIVE" | "PAPER"} />
      ),
    },
    {
      accessorKey: "created_at",
      header: "Time",
      cell: ({ row }) => (
        <span className="text-xs text-muted-foreground">
          {formatDateTime(row.original.created_at)}
        </span>
      ),
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => {
        const o = row.original;
        if (!CANCELLABLE_STATES.has(o.state)) return null;
        return (
          <button
            className="text-xs px-2 py-1 rounded bg-loss/10 text-loss hover:bg-loss/20"
            onClick={() =>
              cancel.mutate(o.order_id, {
                onSuccess: () => toast.success("Order cancelled"),
              })
            }
          >
            Cancel
          </button>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{data?.total ?? 0} orders</span>
        <div className="flex gap-2">
          {(["OPEN", "PENDING", "FILLED", "CANCELLED"] as const).map((s) => (
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
              {s}
            </button>
          ))}
        </div>
      </div>
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <DataTable
          columns={columns}
          data={data?.orders ?? []}
          emptyMessage="No orders"
        />
      )}
    </div>
  );
}
