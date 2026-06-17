"use client";

import { useState } from "react";
import { useCapitalAllocations, useActiveAllocation, useEffectiveAccountState, useCapitalMutations } from "@/hooks/use-capital-framework";
import { MetricTile } from "@/components/shared/metric-tile";
import { StatusIndicator } from "@/components/shared/status-indicator";
import { DataTable } from "@/components/shared/data-table";
import { formatCurrency, formatDateTime } from "@/lib/utils";
import { toast } from "sonner";
import { DollarSign, Plus, Pencil, X } from "lucide-react";
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

const defaultForm = {
  name: "",
  description: "",
  allocated_capital: "",
  capital_source_mode: "HYBRID",
  allocation_type: "GLOBAL",
  universe_scope: "ALL_FNO",
};

export function CapitalView() {
  const { data: allocations, isLoading } = useCapitalAllocations();
  const { data: active } = useActiveAllocation();
  const { data: eas } = useEffectiveAccountState();
  const { createAllocation, activateAllocation, updateCapital } = useCapitalMutations();

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(defaultForm);
  const [editCapital, setEditCapital] = useState<{ id: string; value: string } | null>(null);

  function handleField(e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) {
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const capital = parseFloat(form.allocated_capital);
    if (!form.name.trim() || isNaN(capital) || capital <= 0) {
      toast.error("Name and a positive capital amount are required");
      return;
    }
    createAllocation.mutate(
      {
        name: form.name.trim(),
        description: form.description.trim(),
        allocated_capital: capital,
        capital_source_mode: form.capital_source_mode,
        allocation_type: form.allocation_type,
        universe_scope: form.universe_scope,
      } as Partial<CapitalAllocation>,
      {
        onSuccess: () => {
          toast.success("Allocation created");
          setForm(defaultForm);
          setShowCreate(false);
        },
        onError: (err: unknown) => toast.error((err as Error).message ?? "Failed to create allocation"),
      }
    );
  }

  function handleUpdateCapital(e: React.FormEvent) {
    e.preventDefault();
    if (!editCapital) return;
    const amount = parseFloat(editCapital.value);
    if (isNaN(amount) || amount <= 0) {
      toast.error("Enter a valid capital amount");
      return;
    }
    updateCapital.mutate(
      { id: editCapital.id, amount },
      {
        onSuccess: () => {
          toast.success("Capital updated");
          setEditCapital(null);
        },
        onError: (err: unknown) => toast.error((err as Error).message ?? "Failed to update capital"),
      }
    );
  }

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
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium">Active Allocation — {active.name}</h2>
            <button
              className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20"
              onClick={() => setEditCapital({ id: active.allocation_id, value: String(active.allocated_capital) })}
            >
              <Pencil className="w-3 h-3" /> Edit Capital
            </button>
          </div>
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

          {/* Inline edit capital form */}
          {editCapital && editCapital.id === active.allocation_id && (
            <form onSubmit={handleUpdateCapital} className="mt-4 flex items-center gap-3 border-t pt-3">
              <label className="text-sm text-muted-foreground whitespace-nowrap">New capital (₹):</label>
              <input
                type="number"
                className="flex-1 max-w-[200px] rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                value={editCapital.value}
                onChange={(e) => setEditCapital((prev) => prev ? { ...prev, value: e.target.value } : null)}
                min={1}
                step={1000}
                placeholder="e.g. 500000"
              />
              <button type="submit" disabled={updateCapital.isPending} className="text-xs px-3 py-1.5 rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                {updateCapital.isPending ? "Saving…" : "Save"}
              </button>
              <button type="button" onClick={() => setEditCapital(null)} className="text-xs px-2 py-1.5 rounded hover:bg-muted">
                <X className="w-3 h-3" />
              </button>
            </form>
          )}
        </div>
      )}

      {/* All allocations */}
      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium">Capital Allocations</h2>
          <button
            className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20"
            onClick={() => setShowCreate((v) => !v)}
          >
            {showCreate ? <X className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
            {showCreate ? "Cancel" : "New Allocation"}
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <form onSubmit={handleCreate} className="mb-4 rounded-lg border bg-muted/30 p-4 space-y-3">
            <h3 className="text-xs font-semibold uppercase text-muted-foreground tracking-wide">Create Capital Allocation</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Name *</label>
                <input
                  name="name"
                  value={form.name}
                  onChange={handleField}
                  placeholder="e.g. Main Trading Capital"
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Allocated Capital (₹) *</label>
                <input
                  name="allocated_capital"
                  type="number"
                  value={form.allocated_capital}
                  onChange={handleField}
                  placeholder="e.g. 500000"
                  min={1}
                  step={1000}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Capital Source Mode</label>
                <select
                  name="capital_source_mode"
                  value={form.capital_source_mode}
                  onChange={handleField}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="HYBRID">HYBRID — configured capital + broker margin</option>
                  <option value="CONFIGURED">CONFIGURED — use only allocated capital</option>
                  <option value="ACCOUNT">ACCOUNT — use only live broker capital</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Allocation Type</label>
                <select
                  name="allocation_type"
                  value={form.allocation_type}
                  onChange={handleField}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="GLOBAL">GLOBAL — all strategies</option>
                  <option value="STRATEGY">STRATEGY — specific strategy</option>
                  <option value="PAPER">PAPER — paper trading only</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Universe Scope</label>
                <select
                  name="universe_scope"
                  value={form.universe_scope}
                  onChange={handleField}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="ALL_FNO">ALL_FNO — all NSE F&amp;O instruments</option>
                  <option value="TOP_50_FNO">TOP_50_FNO — top 50 liquid F&amp;O</option>
                  <option value="NIFTY_ONLY">NIFTY_ONLY — Nifty derivatives only</option>
                  <option value="CUSTOM">CUSTOM — operator-defined list</option>
                </select>
              </div>
              <div className="space-y-1 sm:col-span-2">
                <label className="text-xs text-muted-foreground">Description</label>
                <input
                  name="description"
                  value={form.description}
                  onChange={handleField}
                  placeholder="Optional description"
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>
            <div className="flex gap-2 pt-1">
              <button
                type="submit"
                disabled={createAllocation.isPending}
                className="text-xs px-4 py-2 rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {createAllocation.isPending ? "Creating…" : "Create Allocation"}
              </button>
              <button type="button" onClick={() => setShowCreate(false)} className="text-xs px-3 py-2 rounded hover:bg-muted">
                Cancel
              </button>
            </div>
          </form>
        )}

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
