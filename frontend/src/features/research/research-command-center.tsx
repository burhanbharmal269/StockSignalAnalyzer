"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { researchService } from "@/services/research.service";
import type {
  CohortStat,
  Recommendation,
  StrategyHealth,
} from "@/types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(v: number | null | undefined, decimals = 1) {
  if (v == null) return "—";
  return `${v.toFixed(decimals)}%`;
}

function num(v: number | null | undefined, decimals = 2) {
  if (v == null) return "—";
  return v.toFixed(decimals);
}

function clamp(v: number, lo = 0, hi = 100) {
  return Math.max(lo, Math.min(hi, v));
}

function scoreColor(s: number) {
  if (s >= 75) return "text-green-600 dark:text-green-400";
  if (s >= 50) return "text-yellow-600 dark:text-yellow-400";
  return "text-red-600 dark:text-red-400";
}

function trendBadge(t: "IMPROVING" | "STABLE" | "DECLINING") {
  const map = {
    IMPROVING: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    STABLE:    "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    DECLINING: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  };
  return <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${map[t]}`}>{t}</span>;
}

function statusBadge(s: Recommendation["status"]) {
  const map: Record<string, string> = {
    READY_FOR_REVIEW: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300",
    EMERGING:         "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
    WAIT:             "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
    INSUFFICIENT_DATA:"bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${map[s] ?? map.WAIT}`}>
      {s.replace(/_/g, " ")}
    </span>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ScoreArc({ score }: { score: number }) {
  const s = clamp(score);
  return (
    <div className="flex flex-col items-center gap-1">
      <div className={`text-5xl font-bold tabular-nums ${scoreColor(s)}`}>{s.toFixed(0)}</div>
      <div className="text-xs text-muted-foreground">/ 100</div>
      <div className="w-32 h-2 rounded-full bg-muted mt-1">
        <div
          className={`h-2 rounded-full transition-all ${s >= 75 ? "bg-green-500" : s >= 50 ? "bg-yellow-500" : "bg-red-500"}`}
          style={{ width: `${s}%` }}
        />
      </div>
    </div>
  );
}

function HealthCard({ health }: { health: StrategyHealth }) {
  const cats = Object.entries(health.categories || {});
  return (
    <div className="bg-card border rounded-xl p-5 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="font-semibold text-base">Platform Health</h2>
          <p className="text-xs text-muted-foreground mt-0.5">Across 8 operational categories</p>
        </div>
        {trendBadge(health.trend)}
      </div>
      <div className="flex gap-6 items-center">
        <ScoreArc score={health.overall} />
        <div className="flex-1 space-y-2">
          {cats.map(([key, cat]) => (
            <div key={key} className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground capitalize w-28 shrink-0">
                {key.replace(/_/g, " ")}
              </span>
              <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                <div
                  className={`h-1.5 rounded-full ${clamp(cat.score) >= 70 ? "bg-green-500" : clamp(cat.score) >= 45 ? "bg-yellow-500" : "bg-red-500"}`}
                  style={{ width: `${clamp(cat.score)}%` }}
                />
              </div>
              <span className={`text-xs tabular-nums font-medium w-8 text-right ${scoreColor(clamp(cat.score))}`}>
                {clamp(cat.score).toFixed(0)}
              </span>
            </div>
          ))}
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Updated {new Date(health.evaluated_at).toLocaleTimeString()}
      </p>
    </div>
  );
}

function CohortTable({
  title,
  rows,
  emptyMsg = "Not enough data yet",
}: {
  title: string;
  rows: CohortStat[];
  emptyMsg?: string;
}) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground italic">{emptyMsg}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="text-xs w-full">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left py-1 pr-3">Cohort</th>
                <th className="text-right py-1 pr-3">Trades</th>
                <th className="text-right py-1 pr-3">Win%</th>
                <th className="text-right py-1 pr-3">PF</th>
                <th className="text-right py-1">Expect</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.cohort} className="border-b border-border/40 last:border-0 hover:bg-muted/30">
                  <td className="py-1 pr-3 font-medium">{r.cohort}</td>
                  <td className="text-right py-1 pr-3 tabular-nums">{r.trade_count}</td>
                  <td className={`text-right py-1 pr-3 tabular-nums ${r.win_rate >= 50 ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                    {pct(r.win_rate)}
                  </td>
                  <td className={`text-right py-1 pr-3 tabular-nums font-medium ${(r.profit_factor ?? 0) >= 1.2 ? "text-green-600 dark:text-green-400" : ""}`}>
                    {num(r.profit_factor)}
                  </td>
                  <td className="text-right py-1 tabular-nums">
                    {num(r.expectancy, 4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  const [open, setOpen] = useState(false);
  const isOutperform = rec.direction === "OUTPERFORMING";
  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 p-3 hover:bg-muted/40 transition-colors text-left"
      >
        <span className={`text-lg ${isOutperform ? "text-green-500" : "text-red-500"}`}>
          {isOutperform ? "↑" : "↓"}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm">{rec.dimension}</span>
            {rec.cohort_key && (
              <span className="text-xs text-muted-foreground">→ {rec.cohort_key}</span>
            )}
            {statusBadge(rec.status)}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5">
            n={rec.trade_count} · WR {pct(rec.cohort_win_rate)} vs baseline {pct(rec.baseline_win_rate)}
            {rec.z_statistic != null && ` · z=${rec.z_statistic.toFixed(2)}`}
          </div>
        </div>
        <span className="text-muted-foreground text-sm">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="border-t p-3 bg-muted/20 space-y-2 text-xs">
          {rec.message && <p className="text-muted-foreground italic">{rec.message}</p>}
          {rec.expected_improvement && (
            <div><span className="font-medium">Expected improvement:</span> {rec.expected_improvement}</div>
          )}
          {rec.risk_description && (
            <div><span className="font-medium">Risk:</span> {rec.risk_description}</div>
          )}
          {rec.ci_low != null && rec.ci_high != null && (
            <div><span className="font-medium">95% CI:</span> [{pct(rec.ci_low)}, {pct(rec.ci_high)}]</div>
          )}
          {rec.rollback_plan && (
            <div><span className="font-medium">Rollback:</span> {rec.rollback_plan}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main View ─────────────────────────────────────────────────────────────────

const COHORT_DIMS = [
  { key: "score_bucket",        label: "Score Buckets" },
  { key: "regime",              label: "Market Regime" },
  { key: "instrument_type",     label: "Instrument" },
  { key: "time_window",         label: "Time Window" },
  { key: "qualification_grade", label: "Research Grade" },
  { key: "market_context",      label: "Market Context" },
  { key: "day_of_week",         label: "Day of Week" },
  { key: "dte_bucket",          label: "DTE" },
];

export function ResearchCommandCenter() {
  const [activeTab, setActiveTab] = useState<
    "overview" | "cohorts" | "cube" | "recommendations" | "live"
  >("overview");
  const [cubeDims, setCubeDims] = useState(["score_bucket", "regime"]);

  const health = useQuery({
    queryKey:  ["research", "health"],
    queryFn:   () => researchService.getHealth(),
    staleTime: 5 * 60_000,
  });

  const cohorts = useQuery({
    queryKey:  ["research", "cohorts"],
    queryFn:   () => researchService.getAllCohorts(5),
    staleTime: 5 * 60_000,
    enabled:   activeTab === "cohorts" || activeTab === "overview",
  });

  const recs = useQuery({
    queryKey:  ["research", "recommendations"],
    queryFn:   () => researchService.getRecommendations(),
    staleTime: 10 * 60_000,
    enabled:   activeTab === "recommendations" || activeTab === "overview",
  });

  const cube = useQuery({
    queryKey:  ["research", "cube", cubeDims],
    queryFn:   () => researchService.queryCube(cubeDims, 5),
    staleTime: 5 * 60_000,
    enabled:   activeTab === "cube",
  });

  const liveVsPaper = useQuery({
    queryKey:  ["research", "live-vs-paper"],
    queryFn:   () => researchService.getLiveVsPaper(90),
    staleTime: 10 * 60_000,
    enabled:   activeTab === "live",
  });

  const tabs = [
    { id: "overview",         label: "Overview" },
    { id: "cohorts",          label: "Cohort Engine" },
    { id: "cube",             label: "Research Cube" },
    { id: "recommendations",  label: "Recommendations" },
    { id: "live",             label: "Live vs Paper" },
  ] as const;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Research Command Center</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Evidence-driven platform intelligence — Phase 23
          </p>
        </div>
        <a
          href="/api/v1/research/report/weekly/csv"
          download
          className="text-xs px-3 py-1.5 rounded border hover:bg-muted transition-colors"
        >
          Export CSV
        </a>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === t.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Overview ──────────────────────────────────────────────────────── */}
      {activeTab === "overview" && (
        <div className="grid gap-4 lg:grid-cols-2">
          {/* Health */}
          <div className="lg:col-span-2">
            {health.isLoading ? (
              <div className="bg-card border rounded-xl p-5 animate-pulse h-48" />
            ) : health.data ? (
              <HealthCard health={health.data} />
            ) : (
              <div className="bg-card border rounded-xl p-5 text-sm text-muted-foreground">
                Health data unavailable
              </div>
            )}
          </div>

          {/* Top Regimes */}
          <div className="bg-card border rounded-xl p-4">
            <CohortTable
              title="Best Regimes"
              rows={(cohorts.data?.["regime"] ?? []).slice(0, 5)}
            />
          </div>

          {/* Top Score Buckets */}
          <div className="bg-card border rounded-xl p-4">
            <CohortTable
              title="Score Bucket Performance"
              rows={(cohorts.data?.["score_bucket"] ?? []).slice(0, 6)}
            />
          </div>

          {/* Top Instruments */}
          <div className="bg-card border rounded-xl p-4">
            <CohortTable
              title="Instrument Breakdown"
              rows={(cohorts.data?.["instrument_type"] ?? []).slice(0, 5)}
            />
          </div>

          {/* Research Grade */}
          <div className="bg-card border rounded-xl p-4">
            <CohortTable
              title="Research Grade Performance"
              rows={(cohorts.data?.["qualification_grade"] ?? []).slice(0, 6)}
            />
          </div>

          {/* Top Recommendations (compact) */}
          <div className="bg-card border rounded-xl p-4 lg:col-span-2">
            <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">
              Top Recommendations
            </h3>
            {recs.data && recs.data.length > 0 ? (
              <div className="space-y-2">
                {recs.data.slice(0, 3).map((r, i) => (
                  <RecommendationCard key={i} rec={r} />
                ))}
                {recs.data.length > 3 && (
                  <button
                    onClick={() => setActiveTab("recommendations")}
                    className="text-xs text-primary hover:underline"
                  >
                    View all {recs.data.length} recommendations →
                  </button>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground italic">
                No recommendations yet — accumulate more completed trades.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── Cohort Engine ─────────────────────────────────────────────────── */}
      {activeTab === "cohorts" && (
        <div className="grid gap-4 md:grid-cols-2">
          {COHORT_DIMS.map(({ key, label }) => (
            <div key={key} className="bg-card border rounded-xl p-4">
              <CohortTable
                title={label}
                rows={(cohorts.data?.[key] ?? []).slice(0, 8)}
              />
            </div>
          ))}
        </div>
      )}

      {/* ── Research Cube ─────────────────────────────────────────────────── */}
      {activeTab === "cube" && (
        <div className="space-y-4">
          {/* Dimension selector */}
          <div className="bg-card border rounded-xl p-4 space-y-3">
            <h3 className="text-sm font-semibold">Select Dimensions (max 3)</h3>
            <div className="flex flex-wrap gap-2">
              {COHORT_DIMS.map(({ key, label }) => {
                const active = cubeDims.includes(key);
                return (
                  <button
                    key={key}
                    onClick={() => {
                      if (active) {
                        setCubeDims((prev) => prev.filter((d) => d !== key));
                      } else if (cubeDims.length < 3) {
                        setCubeDims((prev) => [...prev, key]);
                      }
                    }}
                    className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                      active
                        ? "bg-primary text-primary-foreground border-primary"
                        : "hover:bg-muted"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Results */}
          <div className="bg-card border rounded-xl p-4">
            {cube.isLoading ? (
              <div className="animate-pulse h-48 bg-muted rounded" />
            ) : !cube.data || cube.data.length === 0 ? (
              <p className="text-sm text-muted-foreground italic">
                No cells with ≥5 completed trades for this combination.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="text-xs w-full">
                  <thead>
                    <tr className="border-b text-muted-foreground">
                      {cubeDims.map((d) => (
                        <th key={d} className="text-left py-1.5 pr-3 capitalize">
                          {d.replace(/_/g, " ")}
                        </th>
                      ))}
                      <th className="text-right py-1.5 pr-3">Trades</th>
                      <th className="text-right py-1.5 pr-3">Win%</th>
                      <th className="text-right py-1.5 pr-3">PF</th>
                      <th className="text-right py-1.5 pr-3">Expect</th>
                      <th className="text-right py-1.5">Sharpe</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cube.data.slice(0, 50).map((row, i) => (
                      <tr key={i} className="border-b border-border/40 last:border-0 hover:bg-muted/30">
                        {cubeDims.map((d) => (
                          <td key={d} className="py-1.5 pr-3 font-medium">{String(row[d] ?? "—")}</td>
                        ))}
                        <td className="text-right py-1.5 pr-3 tabular-nums">{row.trade_count}</td>
                        <td className={`text-right py-1.5 pr-3 tabular-nums ${(row.win_rate ?? 0) >= 50 ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                          {pct(row.win_rate)}
                        </td>
                        <td className={`text-right py-1.5 pr-3 tabular-nums font-medium ${(row.profit_factor ?? 0) >= 1.2 ? "text-green-600 dark:text-green-400" : ""}`}>
                          {num(row.profit_factor)}
                        </td>
                        <td className="text-right py-1.5 pr-3 tabular-nums">{num(row.expectancy, 4)}</td>
                        <td className="text-right py-1.5 tabular-nums">{num(row.sharpe)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {cube.data.length > 50 && (
                  <p className="text-xs text-muted-foreground mt-2">
                    Showing top 50 of {cube.data.length} cells (ordered by PF)
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Recommendations ───────────────────────────────────────────────── */}
      {activeTab === "recommendations" && (
        <div className="space-y-2">
          {recs.isLoading ? (
            <div className="animate-pulse space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-14 bg-muted rounded-lg" />
              ))}
            </div>
          ) : !recs.data || recs.data.length === 0 ? (
            <div className="bg-card border rounded-xl p-6 text-center text-muted-foreground">
              <p className="text-sm">No recommendations available yet.</p>
              <p className="text-xs mt-1">Accumulate ≥30 completed trades per cohort to generate statistically grounded recommendations.</p>
            </div>
          ) : (
            <>
              <div className="bg-card border rounded-xl p-4 flex items-center gap-4 text-sm">
                <div>
                  <span className="font-medium">{recs.data.length}</span>
                  <span className="text-muted-foreground ml-1">total</span>
                </div>
                <div>
                  <span className="font-medium text-blue-600">
                    {recs.data.filter((r) => r.status === "READY_FOR_REVIEW").length}
                  </span>
                  <span className="text-muted-foreground ml-1">ready for review</span>
                </div>
                <div>
                  <span className="font-medium text-amber-600">
                    {recs.data.filter((r) => r.status === "EMERGING").length}
                  </span>
                  <span className="text-muted-foreground ml-1">emerging</span>
                </div>
              </div>
              {recs.data.map((rec, i) => (
                <RecommendationCard key={i} rec={rec} />
              ))}
            </>
          )}
        </div>
      )}

      {/* ── Live vs Paper ─────────────────────────────────────────────────── */}
      {activeTab === "live" && (
        <div className="space-y-4">
          {liveVsPaper.isLoading ? (
            <div className="animate-pulse h-64 bg-muted rounded-xl" />
          ) : !liveVsPaper.data ? (
            <p className="text-sm text-muted-foreground">Could not load comparison data.</p>
          ) : (
            <>
              {!liveVsPaper.data.has_live_data && (
                <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4 text-sm text-amber-800 dark:text-amber-300">
                  No live trading data yet. Gate 2 requires ≥50 completed trades and readiness ≥65 to start live trading.
                </div>
              )}

              {/* Stats comparison */}
              <div className="grid md:grid-cols-2 gap-4">
                {(["paper", "live"] as const).map((mode) => {
                  const s = liveVsPaper.data![mode];
                  return (
                    <div key={mode} className="bg-card border rounded-xl p-4 space-y-3">
                      <h3 className="font-semibold text-sm capitalize">{mode} Trading</h3>
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div className="text-muted-foreground">Completed</div>
                        <div className="font-medium text-right">{s.n}</div>
                        <div className="text-muted-foreground">Win Rate</div>
                        <div className={`font-medium text-right ${s.win_rate >= 50 ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>{pct(s.win_rate)}</div>
                        <div className="text-muted-foreground">Profit Factor</div>
                        <div className="font-medium text-right">{num(s.profit_factor)}</div>
                        <div className="text-muted-foreground">Expectancy</div>
                        <div className="font-medium text-right">{num(s.expectancy, 4)}</div>
                        <div className="text-muted-foreground">A/B Grade %</div>
                        <div className="font-medium text-right">{pct(s.ab_grade_pct)}</div>
                        <div className="text-muted-foreground">Data Quality</div>
                        <div className="font-medium text-right">{num(s.avg_data_quality, 0)}</div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Drift table */}
              {liveVsPaper.data.has_live_data && (
                <div className="bg-card border rounded-xl p-4">
                  <h3 className="font-semibold text-sm mb-3">Drift Analysis</h3>
                  <table className="text-xs w-full">
                    <thead>
                      <tr className="border-b text-muted-foreground">
                        <th className="text-left py-1 pr-3">Metric</th>
                        <th className="text-right py-1 pr-3">Paper</th>
                        <th className="text-right py-1 pr-3">Live</th>
                        <th className="text-right py-1 pr-3">Delta</th>
                        <th className="text-right py-1 pr-3">Direction</th>
                        <th className="text-right py-1">Sig</th>
                      </tr>
                    </thead>
                    <tbody>
                      {liveVsPaper.data.drift_checks.map((d) => (
                        <tr key={d.metric} className="border-b border-border/40 last:border-0">
                          <td className="py-1 pr-3 font-medium">{d.metric.replace(/_/g, " ")}</td>
                          <td className="text-right py-1 pr-3 tabular-nums">{num(d.paper, 3)}</td>
                          <td className="text-right py-1 pr-3 tabular-nums">{num(d.live, 3)}</td>
                          <td className={`text-right py-1 pr-3 tabular-nums ${(d.delta ?? 0) > 0 ? "text-green-600 dark:text-green-400" : (d.delta ?? 0) < 0 ? "text-red-500" : ""}`}>
                            {d.delta != null ? (d.delta > 0 ? "+" : "") + num(d.delta, 3) : "—"}
                          </td>
                          <td className={`text-right py-1 pr-3 text-xs ${d.direction === "IMPROVED" ? "text-green-600 dark:text-green-400" : d.direction === "DEGRADED" ? "text-red-500" : "text-muted-foreground"}`}>
                            {d.direction}
                          </td>
                          <td className={`text-right py-1 text-xs font-medium ${d.significant ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}`}>
                            {d.significant ? "★" : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-xs text-muted-foreground mt-2">★ = statistically significant (p &lt; 0.05)</p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
