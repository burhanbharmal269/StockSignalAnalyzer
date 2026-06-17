"use client";

import { useSignalSummary, useTopSymbols, useSectorBreakdown, useOutcomeCheck } from "@/hooks/use-signal-intelligence";
import { useQuery } from "@tanstack/react-query";
import { executionService } from "@/services/execution.service";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

const VERDICT_COLOR: Record<string, string> = {
  ALWAYS_ON: "text-profit",
  ENABLED: "text-profit",
  DISABLED: "text-warning",
};

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border bg-card p-4 space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function ModeRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={cn("text-xs font-medium px-2 py-0.5 rounded-full bg-muted", VERDICT_COLOR[value] ?? "text-foreground")}>
        {value}
      </span>
    </div>
  );
}

export function SignalAnalyticsView() {
  const { data: mode } = useQuery({
    queryKey: ["execution-status"],
    queryFn: executionService.getStatus,
    refetchInterval: 30_000,
    staleTime: 20_000,
  });
  const { data: summary, isLoading: summaryLoading } = useSignalSummary();
  const { data: topSymbols } = useTopSymbols(10);
  const { data: sectors } = useSectorBreakdown();
  const outcomeCheck = useOutcomeCheck();

  const acceptRate = summary
    ? summary.total > 0
      ? ((summary.accepted / summary.total) * 100).toFixed(1)
      : "0.0"
    : "—";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Signal Analytics</h1>
          <p className="text-sm text-muted-foreground">Always-on signal generation — independent of execution mode</p>
        </div>
        <button
          className="text-xs px-3 py-1.5 rounded border hover:bg-muted disabled:opacity-50"
          onClick={() =>
            outcomeCheck.mutate(undefined, {
              onSuccess: () => toast.success("Outcome check triggered"),
              onError: () => toast.error("Failed to trigger outcome check"),
            })
          }
          disabled={outcomeCheck.isPending}
        >
          {outcomeCheck.isPending ? "Checking…" : "Run Outcome Check"}
        </button>
      </div>

      {/* Execution mode status */}
      {mode && (
        <div className="rounded-lg border bg-card p-4">
          <p className="text-xs font-medium text-muted-foreground mb-3">
            Execution Mode: <span className="text-foreground">{mode.execution_mode}</span>
            {mode.locked && <span className="ml-2 text-warning font-semibold">LOCKED</span>}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-8">
            <ModeRow label="Signal Generation" value={mode.signal_generation} />
            <ModeRow label="Signal Analytics" value={mode.signal_analytics} />
            <ModeRow label="Outcome Tracking" value={mode.outcome_tracking} />
            <ModeRow label="Market Data" value={mode.market_data} />
          </div>
          <p className="text-xs text-muted-foreground mt-3">
            {mode.orders_blocked
              ? "Signals generated + stored + analytics tracked. No orders placed."
              : "Signals generated + stored + analytics tracked. Orders routed to broker."}
          </p>
        </div>
      )}

      {/* Summary stats */}
      {summaryLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : summary ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <StatCard label="Signals Today" value={summary.total} />
          <StatCard label="Accepted" value={summary.accepted} sub={`${acceptRate}% acceptance rate`} />
          <StatCard label="Unique Symbols" value={summary.unique_symbols} />
          <StatCard label="Strategies Active" value={summary.strategies_active} />
          <StatCard label="Avg Score" value={summary.avg_score.toFixed(1)} />
          <StatCard label="Avg Confidence" value={`${summary.avg_confidence.toFixed(1)}%`} />
          <StatCard label="Rejected" value={summary.rejected} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No signal data yet — scanner has not run today.</p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        {/* Top symbols */}
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium mb-3">Top Symbols Today</h2>
          {topSymbols?.top_symbols.length ? (
            <div className="space-y-1.5">
              {topSymbols.top_symbols.map((s) => (
                <div key={s.ticker} className="flex items-center gap-2">
                  <span className="font-mono text-sm w-28 shrink-0">{s.ticker}</span>
                  <div className="flex-1 bg-muted rounded-full h-1.5">
                    <div
                      className="bg-primary h-1.5 rounded-full"
                      style={{
                        width: `${Math.min((s.signal_count / (topSymbols.top_symbols[0]?.signal_count || 1)) * 100, 100)}%`,
                      }}
                    />
                  </div>
                  <span className="text-xs text-muted-foreground tabular-nums w-6 text-right">{s.signal_count}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No data yet</p>
          )}
        </div>

        {/* Sector breakdown */}
        <div className="rounded-lg border bg-card p-4">
          <h2 className="text-sm font-medium mb-3">Sector Breakdown</h2>
          {sectors?.sectors.length ? (
            <div className="space-y-1.5">
              {sectors.sectors.map((s) => (
                <div key={s.sector} className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground truncate pr-4">{s.sector || "INDEX"}</span>
                  <span className="tabular-nums font-medium">{s.accepted}<span className="text-muted-foreground">/{s.total}</span></span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No data yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
