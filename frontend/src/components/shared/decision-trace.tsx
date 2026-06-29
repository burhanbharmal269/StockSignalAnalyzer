"use client";

import { useQuery } from "@tanstack/react-query";
import { analyticsService } from "@/services/analytics.service";
import { cn } from "@/lib/utils";
import type { DecisionTrace as DecisionTraceData, TraceStep } from "@/types";

// ─── Constants ───────────────────────────────────────────────────────────────

const OVERLAY_LABELS: Record<string, string> = {
  market_context:       "Market Context",
  event_overlay:        "Event Calendar",
  regime_stability:     "Regime Stability",
  portfolio_heat:       "Portfolio Heat",
  portfolio_correlation:"Correlation",
  sector_exposure:      "Sector Exposure",
  execution_quality:    "Execution Quality",
};

const GRADE_STYLES: Record<string, string> = {
  A: "bg-profit/10 text-profit border-profit/30",
  B: "bg-warning/10 text-warning border-warning/30",
  C: "bg-orange-500/10 text-orange-400 border-orange-500/30",
  D: "bg-loss/10 text-loss border-loss/30",
};

const CONTEXT_STYLES: Record<string, string> = {
  NORMAL:    "text-profit",
  CAUTION:   "text-warning",
  HIGH_RISK: "text-orange-400",
  PANIC:     "text-loss",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function adjLabel(adj: number): string {
  if (adj === 0) return "±0";
  return adj > 0 ? `+${adj.toFixed(1)}` : `${adj.toFixed(1)}`;
}

function sizeLabel(before: number, after: number): string | null {
  if (Math.abs(after - before) < 0.001) return null;
  return `${(before * 100).toFixed(0)}%→${(after * 100).toFixed(0)}%`;
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function OverlayRow({ step }: { step: TraceStep }) {
  const label = OVERLAY_LABELS[step.name] ?? step.name;
  const sizeDelta = sizeLabel(step.size_before, step.size_after);

  return (
    <tr className={cn(
      "border-b border-border/40 last:border-0",
      !step.applied && "opacity-50"
    )}>
      <td className="py-2 pl-3 pr-2 w-6 text-muted-foreground text-xs tabular-nums">
        {step.step}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        <span className="text-sm font-medium">{label}</span>
        {step.lock && (
          <span className="ml-2 text-xs px-1 rounded bg-loss/10 text-loss border border-loss/30">
            LOCK
          </span>
        )}
      </td>
      <td className="py-2 pr-3">
        <span className={cn(
          "text-xs px-1.5 py-0.5 rounded border font-medium",
          step.applied
            ? "bg-profit/10 text-profit border-profit/30"
            : "bg-muted/40 text-muted-foreground border-border"
        )}>
          {step.applied ? "fired" : "skip"}
        </span>
      </td>
      <td className="py-2 pr-3 tabular-nums text-xs text-right font-mono">
        {step.conf_before.toFixed(1)}
      </td>
      <td className="py-2 pr-3 tabular-nums text-xs text-right font-mono font-semibold">
        <span className={cn(
          step.adj > 0 ? "text-profit" : step.adj < 0 ? "text-loss" : "text-muted-foreground"
        )}>
          {adjLabel(step.adj)}
        </span>
      </td>
      <td className="py-2 pr-3 tabular-nums text-xs text-right font-mono font-semibold">
        {step.conf_after.toFixed(1)}
      </td>
      <td className="py-2 pr-3 text-xs text-muted-foreground">
        {sizeDelta && (
          <span className="text-warning font-mono">{sizeDelta}</span>
        )}
      </td>
      <td className="py-2 pr-3 text-xs text-muted-foreground max-w-[200px] truncate">
        {step.severity && step.severity !== "NONE" && (
          <span className="mr-1.5 font-medium text-warning">[{step.severity}]</span>
        )}
        {step.reason}
      </td>
    </tr>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface DecisionTraceProps {
  signalId: string;
  regime?: string;
}

export function DecisionTrace({ signalId, regime }: DecisionTraceProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["signal-overlay", signalId],
    queryFn: () => analyticsService.getSignalOverlay(signalId),
    staleTime: 60_000,
    retry: false,
  });

  if (isLoading) {
    return (
      <div className="px-4 py-3 text-xs text-muted-foreground animate-pulse">
        Loading decision trace…
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="px-4 py-3 text-xs text-muted-foreground">
        No overlay data recorded for this signal.
      </div>
    );
  }

  let trace: DecisionTraceData | null = null;
  if (data.decision_trace_json) {
    try {
      trace = JSON.parse(data.decision_trace_json) as DecisionTraceData;
    } catch {
      // malformed JSON — degrade gracefully
    }
  }

  const grade = data.execution_grade;
  const gradeStyle = grade ? (GRADE_STYLES[grade] ?? GRADE_STYLES.B) : "";
  const ctxStyle = data.market_context ? (CONTEXT_STYLES[data.market_context] ?? "") : "";

  return (
    <div className="bg-muted/20 border-t border-border/60 px-4 py-3 space-y-3">
      {/* Summary header */}
      <div className="flex flex-wrap gap-4 items-center text-xs">
        {grade && (
          <span className={cn("px-2 py-0.5 rounded border font-bold", gradeStyle)}>
            Grade {grade}
          </span>
        )}
        {data.market_context && (
          <span className={cn("font-medium", ctxStyle)}>
            {data.market_context}
          </span>
        )}
        {regime && (
          <span className="text-muted-foreground">
            Regime: <span className="font-medium text-foreground">{regime}</span>
          </span>
        )}
        {data.regime_stability && (
          <span className="text-muted-foreground">
            Stability: <span className="font-medium text-foreground">{data.regime_stability}</span>
          </span>
        )}
        {trace && (
          <span className="text-muted-foreground">
            <span className="font-mono">{trace.base_confidence.toFixed(1)}</span>
            <span className="mx-1 text-muted-foreground/60">→</span>
            <span className="font-mono font-semibold text-foreground">
              {trace.final_confidence.toFixed(1)}
            </span>
            <span className="ml-1 text-muted-foreground/60">conf</span>
          </span>
        )}
        {trace && Math.abs(trace.final_size_multiplier - 1.0) > 0.001 && (
          <span className="text-muted-foreground">
            Size: <span className="font-mono font-semibold text-warning">
              {(trace.final_size_multiplier * 100).toFixed(0)}%
            </span>
          </span>
        )}
        {data.decision_version && (
          <span className="ml-auto text-muted-foreground/50 font-mono text-[10px]">
            v{data.decision_version}
          </span>
        )}
      </div>

      {/* Overlay steps */}
      {trace && trace.overlays.length > 0 ? (
        <div className="overflow-auto rounded border border-border/40">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-border/40 bg-muted/30 text-[11px] text-muted-foreground">
                <th className="py-1.5 pl-3 pr-2 text-left w-6">#</th>
                <th className="py-1.5 pr-3 text-left">Overlay</th>
                <th className="py-1.5 pr-3 text-left">Status</th>
                <th className="py-1.5 pr-3 text-right">Before</th>
                <th className="py-1.5 pr-3 text-right">Adj</th>
                <th className="py-1.5 pr-3 text-right">After</th>
                <th className="py-1.5 pr-3 text-left">Size</th>
                <th className="py-1.5 pr-3 text-left">Reason</th>
              </tr>
            </thead>
            <tbody>
              {trace.overlays.map((step) => (
                <OverlayRow key={step.step} step={step} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Overlay pipeline ran before Phase 21.2 — no step-by-step trace available.
        </p>
      )}
    </div>
  );
}
