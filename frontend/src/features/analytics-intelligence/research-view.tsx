"use client";

import { useState } from "react";
import {
  useCohorts,
  useEdges,
  useLossClusters,
  useWinnerClusters,
  useReplayCoverage,
  useReplayBackfill,
  useRecommendations,
} from "@/hooks/use-analytics-intelligence";
import type {
  CohortEntry,
  EdgeEntry,
  ClusterEntry,
  Recommendation,
} from "@/services/analytics-intelligence.service";

const LOOKBACK_OPTIONS = [30, 60, 90, 180] as const;

const EDGE_COLORS: Record<string, string> = {
  EDGE_DISCOVERED: "bg-emerald-500/15 border-emerald-500/30 text-emerald-400",
  EDGE_WEAK:       "bg-blue-500/15 border-blue-500/30 text-blue-400",
  NO_EDGE:         "bg-slate-700/50 border-slate-600/40 text-slate-500",
  INSUFFICIENT_DATA: "bg-slate-700/30 border-slate-600/20 text-slate-600",
};

const PRIORITY_COLORS: Record<string, string> = {
  HIGH:   "bg-red-500/15 border-red-500/30 text-red-400",
  MEDIUM: "bg-amber-500/15 border-amber-500/30 text-amber-400",
  LOW:    "bg-blue-500/15 border-blue-500/30 text-blue-400",
};

function EdgeBadge({ edge }: { edge: string }) {
  return (
    <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-semibold ${EDGE_COLORS[edge] ?? "text-slate-400"}`}>
      {edge.replace(/_/g, " ")}
    </span>
  );
}

function CohortTable({ entries, title }: { entries: CohortEntry[]; title: string }) {
  if (!entries.length) return <p className="text-sm text-slate-500">No data</p>;
  return (
    <div>
      <h3 className="mb-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
              <th className="pb-2 text-left">Dimension</th>
              <th className="pb-2 text-left">Bucket</th>
              <th className="pb-2 text-right">n</th>
              <th className="pb-2 text-right">Win %</th>
              <th className="pb-2 text-right">PF</th>
              <th className="pb-2 text-right">Expectancy</th>
              <th className="pb-2 text-right">Sharpe</th>
              <th className="pb-2 text-right">Edge</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/30">
            {entries.map((e, i) => (
              <tr key={`${e.cohort_type}-${e.bucket}-${i}`} className="hover:bg-slate-700/20">
                <td className="py-2 text-slate-500 text-xs">{e.cohort_type}</td>
                <td className="py-2 font-medium text-slate-200">{e.bucket}</td>
                <td className="py-2 text-right tabular-nums text-slate-400">{e.count}</td>
                <td className="py-2 text-right tabular-nums">
                  {e.win_rate_pct != null ? (
                    <span className={e.win_rate_pct >= 50 ? "text-emerald-400" : "text-red-400"}>
                      {e.win_rate_pct.toFixed(1)}%
                    </span>
                  ) : "—"}
                </td>
                <td className="py-2 text-right tabular-nums text-slate-300">
                  {e.profit_factor != null ? `${e.profit_factor.toFixed(2)}×` : "—"}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {e.expectancy_pct != null ? (
                    <span className={e.expectancy_pct >= 0 ? "text-emerald-400" : "text-red-400"}>
                      {e.expectancy_pct.toFixed(3)}%
                    </span>
                  ) : "—"}
                </td>
                <td className="py-2 text-right tabular-nums text-slate-400">
                  {e.sharpe != null ? e.sharpe.toFixed(2) : "—"}
                </td>
                <td className="py-2 text-right">
                  <EdgeBadge edge={e.edge} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function EdgeTable({ edges, title }: { edges: EdgeEntry[]; title: string }) {
  if (!edges.length) return <p className="text-sm text-slate-500">No qualifying edges (need ≥10 trades)</p>;
  return (
    <div>
      <h3 className="mb-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
              <th className="pb-2 text-left">Score</th>
              <th className="pb-2 text-left">Regime</th>
              <th className="pb-2 text-left">MTF</th>
              <th className="pb-2 text-right">n</th>
              <th className="pb-2 text-right">Win %</th>
              <th className="pb-2 text-right">PF</th>
              <th className="pb-2 text-right">Edge</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/30">
            {edges.slice(0, 20).map((e, i) => (
              <tr key={i} className="hover:bg-slate-700/20">
                <td className="py-2 text-slate-300 font-mono text-xs">{e.score_bucket}</td>
                <td className="py-2 text-slate-300 text-xs">{e.regime}</td>
                <td className="py-2 text-slate-400 text-xs">{e.mtf_cohort}</td>
                <td className="py-2 text-right tabular-nums text-slate-400">{e.count}</td>
                <td className="py-2 text-right tabular-nums">
                  {e.win_rate != null ? (
                    <span className={e.win_rate >= 50 ? "text-emerald-400" : "text-red-400"}>
                      {e.win_rate.toFixed(1)}%
                    </span>
                  ) : "—"}
                </td>
                <td className="py-2 text-right tabular-nums text-slate-300">
                  {e.profit_factor != null ? `${e.profit_factor.toFixed(2)}×` : "—"}
                </td>
                <td className="py-2 text-right">
                  <EdgeBadge edge={e.edge} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ClusterList({ clusters, isLoss }: { clusters: ClusterEntry[]; isLoss: boolean }) {
  if (!clusters.length) return <p className="text-sm text-slate-500">No clusters found</p>;
  return (
    <div className="space-y-3">
      {clusters.map((c, i) => (
        <div
          key={i}
          className={`rounded-lg border px-4 py-3 ${
            isLoss
              ? "border-red-500/20 bg-red-500/5"
              : "border-emerald-500/20 bg-emerald-500/5"
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-slate-200">{c.pattern}</p>
              {c.description && <p className="mt-0.5 text-xs text-slate-500">{c.description}</p>}
              {c.components && c.components.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {c.components.map((comp) => (
                    <span key={comp} className="rounded bg-slate-700/60 px-1.5 py-0.5 text-xs text-slate-400">
                      {comp}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="shrink-0 text-right">
              <p className="text-sm font-semibold tabular-nums text-slate-300">n={c.count}</p>
              {isLoss
                ? c.loss_rate_pct != null && (
                    <p className="text-xs text-red-400">{c.loss_rate_pct.toFixed(1)}% loss rate</p>
                  )
                : c.win_rate_pct != null && (
                    <p className="text-xs text-emerald-400">{c.win_rate_pct.toFixed(1)}% win rate</p>
                  )
              }
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function RecommendationCard({ rec }: { rec: Recommendation }) {
  return (
    <div className={`rounded-lg border px-4 py-3 ${PRIORITY_COLORS[rec.priority] ?? "border-slate-700/60 bg-slate-800/50 text-slate-300"}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="text-xs font-medium uppercase opacity-70">
            {rec.priority} · {rec.category}
          </span>
          <p className="mt-0.5 font-medium">{rec.title}</p>
          <p className="mt-1 text-xs opacity-80 leading-relaxed">{rec.description}</p>
        </div>
        {rec.metric_value != null && (
          <div className="shrink-0 text-right">
            <p className="text-lg font-semibold">{typeof rec.metric_value === "number" ? rec.metric_value.toFixed(2) : rec.metric_value}</p>
            {rec.metric_label && <p className="text-xs opacity-60">{rec.metric_label}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ResearchView() {
  const [lookback, setLookback] = useState(90);
  const [tab, setTab] = useState<"cohorts" | "edges" | "clusters" | "replay" | "recommendations">("cohorts");
  const [cohortDim, setCohortDim] = useState<"score" | "confidence" | "mtf" | "regime" | "time_window" | "dte">("score");

  const cohorts = useCohorts(lookback);
  const edges = useEdges(lookback);
  const lossClusters = useLossClusters(lookback);
  const winnerClusters = useWinnerClusters(lookback);
  const replayCoverage = useReplayCoverage();
  const replayBackfill = useReplayBackfill();
  const recommendations = useRecommendations(lookback);

  const tabs = [
    { id: "cohorts",         label: "Cohorts" },
    { id: "edges",           label: "Edge Discovery" },
    { id: "clusters",        label: "Clusters" },
    { id: "replay",          label: "Replay" },
    { id: "recommendations", label: "Recommendations" },
  ] as const;

  const cohortDims = ["score", "confidence", "mtf", "regime", "time_window", "dte"] as const;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Research Intelligence</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Phase 20.6 — cohort analysis, edge discovery, loss patterns, replay timelines
          </p>
        </div>
        <select
          value={lookback}
          onChange={(e) => setLookback(Number(e.target.value))}
          className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200"
        >
          {LOOKBACK_OPTIONS.map((d) => (
            <option key={d} value={d}>{d}d</option>
          ))}
        </select>
      </div>

      <div className="border-b border-slate-700/60">
        <nav className="flex gap-6">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`border-b-2 pb-2 text-sm font-medium transition-colors ${
                tab === t.id
                  ? "border-blue-500 text-blue-400"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Cohorts */}
      {tab === "cohorts" && (
        <div className="space-y-5">
          {/* Top / Bottom quick view */}
          {cohorts.data && (
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                <CohortTable entries={cohorts.data.top_10_cohorts} title="Top 10 Cohorts (by expectancy)" />
              </div>
              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                <CohortTable entries={cohorts.data.bottom_10_cohorts} title="Bottom 10 Cohorts" />
              </div>
            </div>
          )}

          {/* Dimension drill-down */}
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Drill by Dimension
              </h2>
              <div className="flex gap-1 flex-wrap">
                {cohortDims.map((d) => (
                  <button
                    key={d}
                    onClick={() => setCohortDim(d)}
                    className={`rounded px-2 py-1 text-xs transition-colors ${
                      cohortDim === d
                        ? "bg-blue-600 text-white"
                        : "bg-slate-700 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </div>
            {cohorts.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : cohorts.data ? (
              <CohortTable
                entries={cohorts.data.cohorts[cohortDim] ?? []}
                title={`${cohortDim} cohorts`}
              />
            ) : null}
          </div>
        </div>
      )}

      {/* Edges */}
      {tab === "edges" && (
        <div className="space-y-5">
          {edges.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : edges.data ? (
            <>
              <div className="grid gap-5 lg:grid-cols-2">
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                  <EdgeTable edges={edges.data.top_edges ?? []} title="Top Discovered Edges" />
                </div>
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                  <EdgeTable edges={edges.data.worst_edges ?? []} title="Worst Performing Combos" />
                </div>
              </div>
              <div className="grid gap-5 lg:grid-cols-2">
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                  <EdgeTable edges={edges.data.time_window_edges ?? []} title="Time Window × Regime" />
                </div>
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                  <EdgeTable edges={edges.data.double_confirmation_edges ?? []} title="Score × Confidence Double Confirmation" />
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* Clusters */}
      {tab === "clusters" && (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Loss Patterns (failure clusters)
            </h2>
            {lossClusters.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : (
              <ClusterList clusters={lossClusters.data?.clusters ?? []} isLoss />
            )}
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Winner Patterns (recurring winning setups)
            </h2>
            {winnerClusters.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : (
              <ClusterList clusters={winnerClusters.data?.clusters ?? []} isLoss={false} />
            )}
          </div>
        </div>
      )}

      {/* Replay */}
      {tab === "replay" && (
        <div className="space-y-5">
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Replay Coverage
              </h2>
              <button
                onClick={() => replayBackfill.mutate(300)}
                disabled={replayBackfill.isPending}
                className="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600 disabled:opacity-50"
              >
                {replayBackfill.isPending ? "Backfilling…" : "Run Backfill"}
              </button>
            </div>
            {replayCoverage.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : replayCoverage.data ? (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-3">
                  <div className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-4">
                    <p className="text-xs text-slate-400 uppercase tracking-wider">Total Accepted</p>
                    <p className="mt-1 text-2xl font-semibold text-slate-100">
                      {replayCoverage.data.total_accepted}
                    </p>
                  </div>
                  <div className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-4">
                    <p className="text-xs text-slate-400 uppercase tracking-wider">With Replay</p>
                    <p className="mt-1 text-2xl font-semibold text-emerald-400">
                      {replayCoverage.data.signals_with_replay}
                    </p>
                  </div>
                  <div className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-4">
                    <p className="text-xs text-slate-400 uppercase tracking-wider">Coverage</p>
                    <p className={`mt-1 text-2xl font-semibold ${replayCoverage.data.coverage_pct >= 80 ? "text-emerald-400" : "text-amber-400"}`}>
                      {replayCoverage.data.coverage_pct.toFixed(1)}%
                    </p>
                  </div>
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${replayCoverage.data.coverage_pct >= 80 ? "bg-emerald-500" : "bg-amber-500"}`}
                    style={{ width: `${Math.min(replayCoverage.data.coverage_pct, 100)}%` }}
                  />
                </div>
                {replayBackfill.data && (
                  <p className="text-xs text-slate-500">
                    Last backfill: {replayBackfill.data.processed} processed,
                    {" "}{replayBackfill.data.events_created} events created
                  </p>
                )}
              </div>
            ) : null}
          </div>
          <p className="text-xs text-slate-500">
            To view a specific signal timeline, use the signal ID from the Signals page.
            Full replay viewer coming in a future phase.
          </p>
        </div>
      )}

      {/* Recommendations */}
      {tab === "recommendations" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider text-xs tracking-wider">
              Evidence-Based Recommendations
            </h2>
            <p className="text-xs text-slate-500">
              Read-only — never auto-applied to production strategy
            </p>
          </div>
          {recommendations.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : !recommendations.data?.recommendations?.length ? (
            <p className="text-sm text-slate-500 py-8 text-center">
              No recommendations yet — need more settled signal outcomes
            </p>
          ) : (
            <div className="space-y-3">
              {recommendations.data.recommendations.map((r, i) => (
                <RecommendationCard key={i} rec={r} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
