"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { validationService } from "@/services/validation.service";
import { cn } from "@/lib/utils";
import type {
  BugCheck,
  DeploymentReadiness,
  DriftCheck,
  GoNoGo,
  GoNoGoGate,
  ReadinessCategory,
  ValidationSummaryReport,
} from "@/types";

// ─── Constants ───────────────────────────────────────────────────────────────

const TIER_STYLES: Record<string, string> = {
  NOT_READY:               "text-loss bg-loss/10 border-loss/30",
  LIMITED:                 "text-warning bg-warning/10 border-warning/30",
  READY_FOR_SMALL_CAPITAL: "text-primary bg-primary/10 border-primary/30",
  READY_FOR_SCALING:       "text-profit bg-profit/10 border-profit/30",
};

const TIER_LABELS: Record<string, string> = {
  NOT_READY:               "Not Ready",
  LIMITED:                 "Limited",
  READY_FOR_SMALL_CAPITAL: "Small Capital",
  READY_FOR_SCALING:       "Ready to Scale",
};

const HEALTH_STYLES: Record<string, string> = {
  HEALTHY:         "text-profit",
  NEEDS_ATTENTION: "text-warning",
  CRITICAL:        "text-loss",
};

const SEVERITY_STYLES: Record<string, string> = {
  HIGH:    "text-loss bg-loss/10 border-loss/30",
  MEDIUM:  "text-warning bg-warning/10 border-warning/30",
  OK:      "text-profit bg-profit/10 border-profit/30",
  UNKNOWN: "text-muted-foreground bg-muted/20 border-border",
};

const GATE_LABELS: Record<string, string> = {
  GATE_1: "Paper",
  GATE_2: "1-Lot",
  GATE_3: "2-Lot",
  GATE_4: "Scale",
};

// ─── Sub-components ──────────────────────────────────────────────────────────

function ScoreBar({ score, max }: { score: number; max: number }) {
  const pct = Math.round((score / max) * 100);
  const color =
    pct >= 80 ? "bg-profit" : pct >= 50 ? "bg-primary" : pct >= 25 ? "bg-warning" : "bg-loss";
  const textColor =
    pct >= 80 ? "text-profit" : pct >= 50 ? "text-primary" : pct >= 25 ? "text-warning" : "text-loss";
  return (
    <div className="flex items-center gap-2.5">
      <div className="h-1.5 w-20 rounded-full bg-muted/40 overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className={cn("text-xs tabular-nums font-semibold font-mono", textColor)}>
        {score}/{max}
      </span>
    </div>
  );
}

function CheckItem({ label, check }: { label: string; check: Record<string, unknown> }) {
  const pts   = check.points as number;
  const mx    = check.max as number;
  const full  = pts === mx;
  const zero  = pts === 0;
  const meta: string[] = [];
  if (check.status)     meta.push(String(check.status));
  if (typeof check.latency_ms === "number") meta.push(`${check.latency_ms}ms`);
  if (typeof check.age_minutes === "number") meta.push(`${check.age_minutes}min ago`);
  if (typeof check.age_hours === "number")   meta.push(`${check.age_hours}h ago`);
  if (typeof check.value === "number")       meta.push(String(check.value));
  if (typeof check.value === "string")       meta.push(check.value);

  return (
    <div className="flex items-center justify-between gap-2 py-0.5">
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={cn("text-[10px] shrink-0", full ? "text-profit" : zero ? "text-loss" : "text-warning")}>
          {full ? "✓" : zero ? "✗" : "◑"}
        </span>
        <span className="text-[11px] text-foreground/80 capitalize truncate">
          {label.replace(/_/g, " ")}
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {meta.length > 0 && (
          <span className="text-[10px] text-muted-foreground/60 font-mono">{meta.join(" · ")}</span>
        )}
        <span className={cn("text-[11px] font-semibold font-mono w-8 text-right",
          full ? "text-profit" : zero ? "text-loss" : "text-warning")}>
          {pts}/{mx}
        </span>
      </div>
    </div>
  );
}

function CategoryCard({ name, cat }: { name: string; cat: ReadinessCategory }) {
  const label = name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const pct   = Math.round((cat.score / cat.max) * 100);
  const borderColor =
    pct >= 80 ? "border-profit/30" : pct >= 50 ? "border-primary/20" : pct >= 25 ? "border-warning/30" : "border-loss/30";
  const bgColor =
    pct >= 80 ? "bg-profit/5" : pct >= 50 ? "bg-primary/5" : pct >= 25 ? "bg-warning/5" : "bg-loss/5";

  return (
    <div className={cn("rounded-lg border p-3.5 space-y-2.5", borderColor, bgColor)}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold tracking-tight">{label}</span>
        <ScoreBar score={cat.score} max={cat.max} />
      </div>
      <div className="border-t border-border/30 pt-2 space-y-0.5">
        {Object.entries(cat.checks).map(([key, check]) => (
          <CheckItem key={key} label={key} check={check as Record<string, unknown>} />
        ))}
      </div>
    </div>
  );
}

function ReadinessPanel({ data }: { data: DeploymentReadiness }) {
  const score = data.total_score;
  const scoreCls = score >= 75 ? "text-profit" : score >= 50 ? "text-primary" : score >= 30 ? "text-warning" : "text-loss";
  const gatesPassed = Object.values(data.categories).filter(
    (c) => (c as ReadinessCategory).score === (c as ReadinessCategory).max
  ).length;

  return (
    <div className="space-y-5">
      {/* Score header */}
      <div className="flex items-center gap-5 flex-wrap">
        <div className="flex items-end gap-1 leading-none">
          <span className={cn("text-5xl font-bold tabular-nums font-mono", scoreCls)}>{score}</span>
          <span className="text-xl text-muted-foreground mb-1">/100</span>
        </div>
        <div className="space-y-1.5">
          <span className={cn("inline-block px-3 py-1 rounded-full border text-sm font-semibold", TIER_STYLES[data.tier])}>
            {TIER_LABELS[data.tier] ?? data.tier}
          </span>
          <div className="h-2 w-48 rounded-full bg-muted/40 overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all",
                score >= 75 ? "bg-profit" : score >= 50 ? "bg-primary" : score >= 30 ? "bg-warning" : "bg-loss"
              )}
              style={{ width: `${score}%` }}
            />
          </div>
        </div>
        <div className="text-xs text-muted-foreground ml-2">
          {gatesPassed}/{Object.keys(data.categories).length} categories fully passing
        </div>
      </div>

      {/* Category cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {Object.entries(data.categories).map(([key, cat]) => (
          <CategoryCard key={key} name={key} cat={cat as ReadinessCategory} />
        ))}
      </div>
    </div>
  );
}

function GateRow({ gate }: { gate: GoNoGoGate }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cn("rounded border overflow-hidden", gate.passed ? "border-profit/30" : "border-border/60")}>
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-muted/20 transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <span
          className={cn(
            "text-xs font-bold px-2 py-0.5 rounded border",
            gate.passed ? "bg-profit/10 text-profit border-profit/30" : "bg-muted/20 text-muted-foreground border-border"
          )}
        >
          {GATE_LABELS[gate.gate] ?? gate.gate}
        </span>
        <span className="text-sm font-medium">{gate.label}</span>
        <span className={cn("ml-auto text-xs font-bold", gate.passed ? "text-profit" : "text-muted-foreground")}>
          {gate.passed ? "PASS" : "FAIL"}
        </span>
        <span className="text-xs text-muted-foreground">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-4 pb-4 space-y-3 bg-muted/10">
          <div className="space-y-1">
            {(gate.criteria ?? []).map((c, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <span className={cn("font-bold", c.passed ? "text-profit" : "text-loss")}>
                  {c.passed ? "✓" : "✗"}
                </span>
                <span className="text-muted-foreground">{c.criterion}</span>
                <span className="ml-auto font-mono">
                  <span className="text-muted-foreground/60 mr-1">{c.required}</span>
                  <span className={cn("font-semibold", c.passed ? "text-profit" : "text-loss")}>
                    {String(c.actual)}
                  </span>
                </span>
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground border-t border-border/40 pt-2">
            {gate.explanation}
          </p>
        </div>
      )}
    </div>
  );
}

function GoNoGoPanel({ data }: { data: GoNoGo }) {
  const stats = data.trade_stats;
  return (
    <div className="space-y-4">
      <div className="rounded border border-border/60 p-4 bg-muted/10 space-y-2">
        <p className="text-sm font-medium leading-relaxed">{data.recommendation}</p>
        <div className="flex gap-4 text-xs text-muted-foreground flex-wrap pt-1">
          <span>Trades: <span className="font-mono text-foreground">{stats?.n ?? 0}</span></span>
          <span>Win rate: <span className="font-mono text-foreground">{stats?.win_rate_pct != null ? `${stats.win_rate_pct.toFixed(1)}%` : "—"}</span></span>
          {stats?.profit_factor != null && (
            <span>PF: <span className="font-mono text-foreground">{stats.profit_factor.toFixed(2)}</span></span>
          )}
        </div>
      </div>
      <div className="space-y-2">
        {(data.gates ?? []).map((gate) => (
          <GateRow key={gate.gate} gate={gate} />
        ))}
      </div>
    </div>
  );
}

function BugCard({ check }: { check: BugCheck }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className={cn(
        "rounded border overflow-hidden",
        check.detected && check.severity === "HIGH" ? "border-loss/40" :
        check.detected && check.severity === "MEDIUM" ? "border-warning/40" :
        "border-border/60"
      )}
    >
      <button
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-muted/20 transition-colors"
        onClick={() => setOpen((v) => !v)}
      >
        <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border", SEVERITY_STYLES[check.severity])}>
          {check.severity}
        </span>
        <span className="text-xs font-mono truncate">{check.pattern}</span>
        {check.detected && (
          <span className="ml-auto text-xs font-bold text-loss">DETECTED</span>
        )}
        {!check.detected && (
          <span className="ml-auto text-xs text-profit">OK</span>
        )}
        <span className="text-xs text-muted-foreground">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 bg-muted/5">
          <p className="text-xs text-muted-foreground">{check.description}</p>
          {check.detected && check.recommendation && (
            <p className="text-xs text-warning border-l-2 border-warning/40 pl-2">
              {check.recommendation}
            </p>
          )}
          <div className="font-mono text-[10px] text-muted-foreground/70 bg-muted/20 rounded p-2">
            {Object.entries(check.evidence).map(([k, v]) => (
              <div key={k}>
                <span className="text-muted-foreground">{k}: </span>
                {String(v)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function BugDetectionPanel({ data }: { data: import("@/types").BugDetection }) {
  const { summary, checks } = data;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4 text-sm">
        <span className={cn("font-semibold", summary.system_healthy ? "text-profit" : "text-loss")}>
          {summary.system_healthy ? "No issues detected" : `${summary.detected} pattern(s) detected`}
        </span>
        {summary.high_severity > 0 && (
          <span className="text-xs text-loss font-bold">{summary.high_severity} HIGH</span>
        )}
        <span className="text-xs text-muted-foreground ml-auto">{summary.total_checks} checks</span>
      </div>
      <div className="space-y-1.5">
        {checks.map((c, i) => (
          <BugCard key={i} check={c} />
        ))}
      </div>
    </div>
  );
}

function DriftRow({ d, highlight }: { d: DriftCheck; highlight: boolean }) {
  const label = d.metric.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const sig   = d.significance === "SIGNIFICANT";
  const dir   = d.direction;
  const chgPos = d.pct_change != null && d.pct_change > 0;
  const chgNeg = d.pct_change != null && d.pct_change < 0;

  return (
    <tr className={cn(
      "border-b border-border/40 last:border-0 transition-colors",
      highlight && sig && dir === "DEGRADED" ? "bg-loss/5" :
      highlight && sig && dir === "IMPROVED" ? "bg-profit/5" :
      "hover:bg-muted/20"
    )}>
      <td className="py-2.5 pl-3 pr-4 text-xs font-semibold whitespace-nowrap text-foreground">
        {label}
        {sig && (
          <span className={cn("ml-1.5 text-[10px] font-bold px-1 py-0.5 rounded",
            dir === "IMPROVED" ? "bg-profit/10 text-profit" : "bg-loss/10 text-loss")}>
            {dir === "IMPROVED" ? "▲ IMPROVED" : "▼ DEGRADED"}
          </span>
        )}
      </td>
      <td className="py-2.5 pr-4 tabular-nums text-xs text-right font-mono text-muted-foreground">
        {d.reference != null ? d.reference.toFixed(2) : "—"}
      </td>
      <td className={cn("py-2.5 pr-4 tabular-nums text-xs text-right font-mono font-semibold",
        sig && dir === "IMPROVED" ? "text-profit" :
        sig && dir === "DEGRADED" ? "text-loss" :
        "text-foreground"
      )}>
        {d.comparison != null ? d.comparison.toFixed(2) : "—"}
      </td>
      <td className="py-2.5 pr-4 tabular-nums text-xs text-right font-mono">
        {d.pct_change != null ? (
          <span className={cn(
            "font-semibold",
            chgPos ? "text-profit" : chgNeg ? "text-loss" : "text-muted-foreground"
          )}>
            {chgPos ? "+" : ""}{d.pct_change.toFixed(1)}%
          </span>
        ) : <span className="text-muted-foreground">—</span>}
      </td>
      <td className="py-2.5 pr-3 tabular-nums text-[11px] text-right font-mono">
        <span className={cn(
          sig ? "font-semibold" : "text-muted-foreground/50"
        )}>
          z={d.z_stat.toFixed(2)}
        </span>
      </td>
    </tr>
  );
}

// ─── Tab types ────────────────────────────────────────────────────────────────

type Tab = "overview" | "readiness" | "go-no-go" | "bugs" | "drift";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview",  label: "Overview" },
  { id: "go-no-go",  label: "Go / No-Go" },
  { id: "readiness", label: "Readiness" },
  { id: "bugs",      label: "Bug Detection" },
  { id: "drift",     label: "Drift" },
];

// ─── Main View ────────────────────────────────────────────────────────────────

export function ValidationView() {
  const [tab, setTab] = useState<Tab>("overview");

  const summaryQ = useQuery({
    queryKey: ["validation", "summary"],
    queryFn:  validationService.getSummaryReport,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const driftQ = useQuery({
    queryKey: ["validation", "drift"],
    queryFn:  () => validationService.getDrift(),
    staleTime: 10 * 60_000,
    retry: false,
    enabled: tab === "drift",
  });

  const summary = summaryQ.data as ValidationSummaryReport | undefined;
  const health  = summary?.health_summary;

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-base font-semibold">Validation & Readiness</h1>
          <p className="text-xs text-muted-foreground">Read-only evidence framework — Phase 22</p>
        </div>
        {health && (
          <span className={cn("text-xs font-bold uppercase tracking-wide", HEALTH_STYLES[health.overall])}>
            {health.overall.replace("_", " ")}
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border/60 pb-0">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "text-xs px-3 py-2 -mb-px border-b-2 transition-colors",
              tab === t.id
                ? "border-primary text-primary font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Loading / error */}
      {summaryQ.isLoading && (
        <p className="text-sm text-muted-foreground animate-pulse">Loading validation data…</p>
      )}
      {summaryQ.isError && (
        <p className="text-sm text-destructive">Failed to load validation data — backend may be unavailable</p>
      )}

      {/* Overview tab — health summary */}
      {tab === "overview" && health && summary && (
        <div className="space-y-4">
          {/* Health banner */}
          <div className={cn(
            "rounded-lg border p-4 space-y-2",
            health.overall === "HEALTHY" ? "border-profit/30 bg-profit/5" :
            health.overall === "CRITICAL" ? "border-loss/30 bg-loss/5" : "border-warning/30 bg-warning/5"
          )}>
            <div className="flex items-center gap-3 flex-wrap">
              <span className={cn("font-bold", HEALTH_STYLES[health.overall])}>
                {health.overall.replace("_", " ")}
              </span>
              <span className={cn("text-xs px-2 py-0.5 rounded border font-semibold", TIER_STYLES[health.tier])}>
                {TIER_LABELS[health.tier] ?? health.tier} — {health.score}/100
              </span>
              {health.gate && (
                <span className="text-xs text-profit font-medium">
                  Gate: {health.gate.replace("GATE_", "G")} cleared
                </span>
              )}
            </div>
            <p className="text-sm leading-relaxed">{health.recommendation}</p>
            {health.issues.length > 0 && (
              <ul className="space-y-1">
                {health.issues.map((i, idx) => (
                  <li key={idx} className="text-xs text-loss flex gap-2">
                    <span>✗</span><span>{i}</span>
                  </li>
                ))}
              </ul>
            )}
            {health.warnings.length > 0 && (
              <ul className="space-y-1">
                {health.warnings.map((w, idx) => (
                  <li key={idx} className="text-xs text-warning flex gap-2">
                    <span>⚠</span><span>{w}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Quick stats row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Readiness", value: `${health.score}/100`, sub: health.tier.replace(/_/g, " ") },
              { label: "Trades",    value: String(summary.go_no_go.trade_stats?.n ?? 0), sub: "completed" },
              { label: "Win Rate",  value: summary.go_no_go.trade_stats?.win_rate_pct != null ? `${summary.go_no_go.trade_stats.win_rate_pct.toFixed(1)}%` : "—", sub: "" },
              {
                label: "Profit Factor",
                value: summary.go_no_go.trade_stats?.profit_factor?.toFixed(2) ?? "—",
                sub: "",
              },
            ].map((s) => (
              <div key={s.label} className="rounded border border-border/60 p-3 space-y-1">
                <p className="text-[11px] text-muted-foreground">{s.label}</p>
                <p className="text-xl font-bold font-mono tabular-nums">{s.value}</p>
                {s.sub && <p className="text-[10px] text-muted-foreground/60">{s.sub}</p>}
              </div>
            ))}
          </div>

          {/* Bug summary inline */}
          {summary.bug_detection.summary.detected > 0 && (
            <div className="rounded border border-loss/30 bg-loss/5 px-4 py-3 text-xs space-y-1">
              <p className="font-semibold text-loss">
                {summary.bug_detection.summary.detected} silent failure(s) detected
              </p>
              {summary.bug_detection.checks
                .filter((c) => c.detected)
                .map((c, i) => (
                  <p key={i} className="text-muted-foreground">• {c.pattern}: {c.description}</p>
                ))}
            </div>
          )}
        </div>
      )}

      {/* Readiness tab */}
      {tab === "readiness" && summary?.deployment_readiness && (
        <ReadinessPanel data={summary.deployment_readiness} />
      )}

      {/* Go/No-Go tab */}
      {tab === "go-no-go" && summary?.go_no_go && (
        <GoNoGoPanel data={summary.go_no_go} />
      )}

      {/* Bug detection tab */}
      {tab === "bugs" && summary?.bug_detection && (
        <BugDetectionPanel data={summary.bug_detection} />
      )}

      {/* Drift tab */}
      {tab === "drift" && (
        <>
          {driftQ.isLoading && (
            <p className="text-sm text-muted-foreground animate-pulse">Loading drift data…</p>
          )}
          {driftQ.data && (() => {
            const drift = driftQ.data as import("@/types").ProductionDrift;
            const drifted = drift.summary.significant_drifts;
            return (
              <div className="space-y-4">
                {/* Summary bar */}
                <div className="flex items-center gap-3 flex-wrap">
                  <div className="flex gap-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <span className="font-medium text-foreground/70">Ref:</span>
                      {drift.periods.reference.start.slice(0, 10)} → {drift.periods.reference.end.slice(0, 10)}
                    </span>
                    <span className="text-border">·</span>
                    <span className="flex items-center gap-1">
                      <span className="font-medium text-foreground/70">Now:</span>
                      {drift.periods.comparison.start.slice(0, 10)} → {drift.periods.comparison.end.slice(0, 10)}
                    </span>
                  </div>
                  <span className={cn(
                    "ml-auto text-xs font-bold px-2.5 py-1 rounded-full",
                    drifted === 0
                      ? "bg-profit/10 text-profit"
                      : drifted <= 1
                      ? "bg-warning/10 text-warning"
                      : "bg-loss/10 text-loss"
                  )}>
                    {drifted === 0 ? "✓ Stable" : `${drifted} drift${drifted > 1 ? "s" : ""} detected`}
                  </span>
                </div>

                {/* Table */}
                <div className="overflow-auto rounded-lg border border-border/50">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-border/40 bg-muted/30">
                        <th className="py-2.5 pl-3 pr-4 text-left text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Metric</th>
                        <th className="py-2.5 pr-4 text-right text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Reference</th>
                        <th className="py-2.5 pr-4 text-right text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Now</th>
                        <th className="py-2.5 pr-4 text-right text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Change</th>
                        <th className="py-2.5 pr-3 text-right text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">z-score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {drift.drift_checks.map((d, i) => (
                        <DriftRow key={i} d={d} highlight={true} />
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-[11px] text-muted-foreground/50">
                  Significance threshold: |z| ≥ 1.96 (p &lt; 0.05). Inline badge shows direction only for significant drifts.
                </p>
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}
