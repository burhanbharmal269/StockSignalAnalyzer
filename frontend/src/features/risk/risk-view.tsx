"use client";

import { useState } from "react";
import { useRiskProfiles, useActiveRiskProfile, useRiskProfileMutations, useRiskDecisions } from "@/hooks/use-risk";
import { StatusIndicator } from "@/components/shared/status-indicator";
import { DataTable } from "@/components/shared/data-table";
import { formatDateTime } from "@/lib/utils";
import { toast } from "sonner";
import { Plus, X } from "lucide-react";
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

const PRESETS: Record<string, Partial<typeof defaultForm>> = {
  CONSERVATIVE: { risk_per_trade_pct: "1", daily_loss_pct: "2", weekly_loss_pct: "4", drawdown_pct: "8", max_open_positions: "3", max_position_size_pct: "10", min_position_size_lots: "1" },
  MODERATE:     { risk_per_trade_pct: "2", daily_loss_pct: "3", weekly_loss_pct: "6", drawdown_pct: "12", max_open_positions: "5", max_position_size_pct: "20", min_position_size_lots: "1" },
  AGGRESSIVE:   { risk_per_trade_pct: "3", daily_loss_pct: "5", weekly_loss_pct: "10", drawdown_pct: "20", max_open_positions: "8", max_position_size_pct: "30", min_position_size_lots: "1" },
};

const defaultForm = {
  name: "",
  description: "",
  profile_type: "MODERATE",
  universe_scope: "ALL_FNO",
  risk_per_trade_pct: "2",
  max_open_positions: "5",
  daily_loss_pct: "3",
  weekly_loss_pct: "6",
  drawdown_pct: "12",
  max_position_size_pct: "20",
  min_position_size_lots: "1",
};

export function RiskView() {
  const { data: profiles, isLoading: profilesLoading } = useRiskProfiles();
  const { data: active } = useActiveRiskProfile();
  const { data: decisions, isLoading: decisionsLoading } = useRiskDecisions({ page_size: 20 });
  const { create, activate, deactivate } = useRiskProfileMutations();

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(defaultForm);

  function handleField(e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) {
    const { name, value } = e.target;
    if (name === "profile_type" && value !== "CUSTOM") {
      const preset = PRESETS[value];
      if (preset) setForm((f) => ({ ...f, ...preset, profile_type: value }));
      else setForm((f) => ({ ...f, profile_type: value }));
    } else {
      setForm((f) => ({ ...f, [name]: value }));
    }
  }

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      toast.error("Name is required");
      return;
    }
    const payload: Partial<RiskProfile> = {
      name: form.name.trim(),
      description: form.description.trim(),
      profile_type: form.profile_type,
      universe_scope: form.universe_scope,
      risk_per_trade_pct: parseFloat(form.risk_per_trade_pct),
      max_open_positions: parseInt(form.max_open_positions, 10),
      daily_loss_pct: parseFloat(form.daily_loss_pct),
      weekly_loss_pct: parseFloat(form.weekly_loss_pct),
      drawdown_pct: parseFloat(form.drawdown_pct),
      max_position_size_pct: parseFloat(form.max_position_size_pct),
      min_position_size_lots: parseInt(form.min_position_size_lots, 10),
    };
    create.mutate(payload, {
      onSuccess: () => {
        toast.success("Risk profile created");
        setForm(defaultForm);
        setShowCreate(false);
      },
      onError: (err: unknown) => toast.error((err as Error).message ?? "Failed to create profile"),
    });
  }

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
            <div>
              <span className="text-muted-foreground">Daily Loss:</span>{" "}
              <span className="font-medium">{active.daily_loss_pct}%</span>
            </div>
            <div>
              <span className="text-muted-foreground">Weekly Loss:</span>{" "}
              <span className="font-medium">{active.weekly_loss_pct}%</span>
            </div>
            <div>
              <span className="text-muted-foreground">Max Drawdown:</span>{" "}
              <span className="font-medium">{active.drawdown_pct}%</span>
            </div>
            <div>
              <span className="text-muted-foreground">Max Position Size:</span>{" "}
              <span className="font-medium">{active.max_position_size_pct}%</span>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-lg border bg-card p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium">Risk Profiles</h2>
          <button
            className="flex items-center gap-1 text-xs px-2 py-1 rounded bg-primary/10 text-primary hover:bg-primary/20"
            onClick={() => setShowCreate((v) => !v)}
          >
            {showCreate ? <X className="w-3 h-3" /> : <Plus className="w-3 h-3" />}
            {showCreate ? "Cancel" : "New Profile"}
          </button>
        </div>

        {/* Create form */}
        {showCreate && (
          <form onSubmit={handleCreate} className="mb-4 rounded-lg border bg-muted/30 p-4 space-y-3">
            <h3 className="text-xs font-semibold uppercase text-muted-foreground tracking-wide">Create Risk Profile</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Name *</label>
                <input
                  name="name"
                  value={form.name}
                  onChange={handleField}
                  placeholder="e.g. My Trading Risk Profile"
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Profile Type (preset fills defaults)</label>
                <select
                  name="profile_type"
                  value={form.profile_type}
                  onChange={handleField}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="CONSERVATIVE">CONSERVATIVE — tight limits, 1% risk/trade</option>
                  <option value="MODERATE">MODERATE — balanced, 2% risk/trade</option>
                  <option value="AGGRESSIVE">AGGRESSIVE — wider limits, 3% risk/trade</option>
                  <option value="CUSTOM">CUSTOM — all manual</option>
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
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Risk per Trade (%)</label>
                <input
                  name="risk_per_trade_pct"
                  type="number"
                  value={form.risk_per_trade_pct}
                  onChange={handleField}
                  min={0.1}
                  max={10}
                  step={0.1}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Daily Loss Cap (%)</label>
                <input
                  name="daily_loss_pct"
                  type="number"
                  value={form.daily_loss_pct}
                  onChange={handleField}
                  min={0.1}
                  max={20}
                  step={0.1}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Weekly Loss Cap (%)</label>
                <input
                  name="weekly_loss_pct"
                  type="number"
                  value={form.weekly_loss_pct}
                  onChange={handleField}
                  min={0.1}
                  max={30}
                  step={0.1}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Max Drawdown (%)</label>
                <input
                  name="drawdown_pct"
                  type="number"
                  value={form.drawdown_pct}
                  onChange={handleField}
                  min={1}
                  max={50}
                  step={0.5}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Max Open Positions</label>
                <input
                  name="max_open_positions"
                  type="number"
                  value={form.max_open_positions}
                  onChange={handleField}
                  min={1}
                  max={50}
                  step={1}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Max Position Size (% of capital)</label>
                <input
                  name="max_position_size_pct"
                  type="number"
                  value={form.max_position_size_pct}
                  onChange={handleField}
                  min={1}
                  max={100}
                  step={1}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Min Position Size (lots)</label>
                <input
                  name="min_position_size_lots"
                  type="number"
                  value={form.min_position_size_lots}
                  onChange={handleField}
                  min={1}
                  max={10}
                  step={1}
                  className="w-full rounded border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
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
                disabled={create.isPending}
                className="text-xs px-4 py-2 rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {create.isPending ? "Creating…" : "Create Profile"}
              </button>
              <button type="button" onClick={() => setShowCreate(false)} className="text-xs px-3 py-2 rounded hover:bg-muted">
                Cancel
              </button>
            </div>
          </form>
        )}

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
