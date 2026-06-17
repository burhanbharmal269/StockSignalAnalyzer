"use client";

import { useState } from "react";
import { useFilterAnalytics } from "@/hooks/use-signal-intelligence";
import { cn } from "@/lib/utils";
import type { FilterMetrics } from "@/services/signal-intelligence.service";

const LOOKBACK_OPTIONS = [7, 14, 30, 90];

const VERDICT_STYLES: Record<string, string> = {
  IMPROVING: "bg-profit/10 text-profit",
  HURTING: "bg-loss/10 text-loss",
  NEUTRAL: "bg-muted text-muted-foreground",
  INSUFFICIENT_DATA: "bg-muted text-muted-foreground",
};

function FilterRow({ f }: { f: FilterMetrics }) {
  return (
    <tr className="border-b last:border-0 hover:bg-muted/30">
      <td className="py-2.5 pr-4">
        <p className="text-sm font-medium">{f.filter_name}</p>
        <p className="text-xs text-muted-foreground">{f.description}</p>
      </td>
      <td className="py-2.5 pr-4 text-sm tabular-nums text-right">{f.signals_before.toLocaleString()}</td>
      <td className="py-2.5 pr-4 text-sm tabular-nums text-right">{f.signals_after.toLocaleString()}</td>
      <td className="py-2.5 pr-4 text-sm tabular-nums text-right">{f.rejected_count.toLocaleString()}</td>
      <td className="py-2.5 pr-4 text-sm tabular-nums text-right">{f.pass_rate_pct.toFixed(1)}%</td>
      <td className="py-2.5 pr-4 text-sm tabular-nums text-right">
        <span className={f.win_rate_passed >= 50 ? "text-profit" : "text-loss"}>
          {f.win_rate_passed.toFixed(1)}%
        </span>
      </td>
      <td className="py-2.5 pr-4 text-sm tabular-nums text-right text-muted-foreground">
        {f.win_rate_rejected.toFixed(1)}%
      </td>
      <td className="py-2.5 pr-4 text-sm tabular-nums text-right">
        <span className={f.performance_delta > 0 ? "text-profit" : f.performance_delta < 0 ? "text-loss" : "text-muted-foreground"}>
          {f.performance_delta > 0 ? "+" : ""}{f.performance_delta.toFixed(1)}%
        </span>
      </td>
      <td className="py-2.5">
        <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", VERDICT_STYLES[f.verdict] ?? "bg-muted text-muted-foreground")}>
          {f.verdict.replace("_", " ")}
        </span>
      </td>
    </tr>
  );
}

export function FilterAnalyticsView() {
  const [lookback, setLookback] = useState(30);
  const { data: report, isLoading } = useFilterAnalytics(lookback);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Filter Analytics</h1>
          <p className="text-sm text-muted-foreground">Measures whether each filter improves or hurts signal quality</p>
        </div>
        <div className="flex gap-1">
          {LOOKBACK_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setLookback(d)}
              className={cn(
                "text-xs px-2.5 py-1 rounded border",
                lookback === d
                  ? "bg-primary text-primary-foreground border-primary"
                  : "border-border hover:bg-muted"
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !report ? (
        <p className="text-sm text-muted-foreground">No filter data available.</p>
      ) : (
        <>
          {/* Summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="rounded-lg border bg-card p-4">
              <p className="text-xs text-muted-foreground">Signals Evaluated</p>
              <p className="text-2xl font-semibold tabular-nums">{report.total_signals_evaluated.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <p className="text-xs text-muted-foreground">Signals Accepted</p>
              <p className="text-2xl font-semibold tabular-nums text-profit">{report.total_signals_accepted.toLocaleString()}</p>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <p className="text-xs text-muted-foreground">Acceptance Rate</p>
              <p className="text-2xl font-semibold tabular-nums">{report.acceptance_rate.toFixed(1)}%</p>
            </div>
            <div className="rounded-lg border bg-card p-4">
              <p className="text-xs text-muted-foreground">Improving / Hurting</p>
              <p className="text-2xl font-semibold">
                <span className="text-profit">{report.improving_filters.length}</span>
                <span className="text-muted-foreground mx-1">/</span>
                <span className="text-loss">{report.hurting_filters.length}</span>
              </p>
            </div>
          </div>

          {/* Filter table */}
          <div className="rounded-lg border bg-card overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b bg-muted/30">
                  <th className="py-2.5 pr-4 pl-4 text-xs font-medium text-muted-foreground">Filter</th>
                  <th className="py-2.5 pr-4 text-xs font-medium text-muted-foreground text-right">Before</th>
                  <th className="py-2.5 pr-4 text-xs font-medium text-muted-foreground text-right">After</th>
                  <th className="py-2.5 pr-4 text-xs font-medium text-muted-foreground text-right">Rejected</th>
                  <th className="py-2.5 pr-4 text-xs font-medium text-muted-foreground text-right">Pass Rate</th>
                  <th className="py-2.5 pr-4 text-xs font-medium text-muted-foreground text-right">Win Rate (Pass)</th>
                  <th className="py-2.5 pr-4 text-xs font-medium text-muted-foreground text-right">Win Rate (Rej)</th>
                  <th className="py-2.5 pr-4 text-xs font-medium text-muted-foreground text-right">Delta</th>
                  <th className="py-2.5 pr-4 text-xs font-medium text-muted-foreground">Verdict</th>
                </tr>
              </thead>
              <tbody className="pl-4">
                {report.filters.map((f) => (
                  <tr key={f.filter_name} className="border-b last:border-0 hover:bg-muted/30">
                    <td className="py-2.5 pr-4 pl-4">
                      <p className="text-sm font-medium">{f.filter_name}</p>
                      <p className="text-xs text-muted-foreground">{f.description}</p>
                    </td>
                    <td className="py-2.5 pr-4 text-sm tabular-nums text-right">{f.signals_before.toLocaleString()}</td>
                    <td className="py-2.5 pr-4 text-sm tabular-nums text-right">{f.signals_after.toLocaleString()}</td>
                    <td className="py-2.5 pr-4 text-sm tabular-nums text-right">{f.rejected_count.toLocaleString()}</td>
                    <td className="py-2.5 pr-4 text-sm tabular-nums text-right">{f.pass_rate_pct.toFixed(1)}%</td>
                    <td className="py-2.5 pr-4 text-sm tabular-nums text-right">
                      <span className={f.win_rate_passed >= 50 ? "text-profit" : "text-loss"}>
                        {f.win_rate_passed.toFixed(1)}%
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 text-sm tabular-nums text-right text-muted-foreground">
                      {f.win_rate_rejected.toFixed(1)}%
                    </td>
                    <td className="py-2.5 pr-4 text-sm tabular-nums text-right">
                      <span className={f.performance_delta > 0 ? "text-profit" : f.performance_delta < 0 ? "text-loss" : "text-muted-foreground"}>
                        {f.performance_delta > 0 ? "+" : ""}{f.performance_delta.toFixed(1)}%
                      </span>
                    </td>
                    <td className="py-2.5 pr-4">
                      <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", VERDICT_STYLES[f.verdict] ?? "bg-muted text-muted-foreground")}>
                        {f.verdict.replace("_", " ")}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="rounded-lg border bg-card p-4">
            <p className="text-xs font-medium mb-2">How to read the verdicts</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs text-muted-foreground">
              <div><span className="text-profit font-medium">IMPROVING</span> — pass-through signals win ≥5% more than rejected</div>
              <div><span className="text-loss font-medium">HURTING</span> — pass-through signals win ≥5% less (filter is too aggressive)</div>
              <div><span className="font-medium">NEUTRAL</span> — delta within ±5% — filter has minor impact</div>
              <div><span className="font-medium">INSUFFICIENT DATA</span> — fewer than 10 resolved signals</div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
