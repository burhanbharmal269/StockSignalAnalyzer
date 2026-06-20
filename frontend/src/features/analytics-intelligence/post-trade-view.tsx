"use client";

import { useState } from "react";
import {
  useAttributionSummary,
  useAttributionEnrich,
  useEntryExitSummary,
  useComponentPerformance,
  useGateEffectiveness,
} from "@/hooks/use-analytics-intelligence";
import type {
  AttributionReason,
  QualityDistributionEntry,
  ComponentPerformance,
  GateEntry,
} from "@/services/analytics-intelligence.service";

const LOOKBACK_OPTIONS = [7, 14, 30, 90] as const;

const VERDICT_COLORS: Record<string, string> = {
  STRONG: "text-emerald-400",
  EFFECTIVE: "text-emerald-400",
  WEAK: "text-red-400",
  INEFFECTIVE: "text-red-400",
  NEUTRAL: "text-slate-400",
  INSUFFICIENT_DATA: "text-slate-500",
};

const QUALITY_COLORS: Record<string, string> = {
  EXCELLENT: "text-emerald-400",
  GOOD:      "text-blue-400",
  ACCEPTABLE:"text-slate-300",
  WEAK:      "text-amber-400",
  FAILED:    "text-red-400",
};

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-4">
      <p className="text-xs text-slate-400 uppercase tracking-wider">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-100">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function HBar({ reason, count, total, colorClass }: {
  reason: string; count: number; total: number; colorClass: string;
}) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-slate-400 w-48 shrink-0 truncate" title={reason}>
        {reason.replace(/_/g, " ")}
      </span>
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-slate-400 w-8 text-right">{count}</span>
    </div>
  );
}

function ReasonList({ reasons, colorClass, emptyText }: {
  reasons: AttributionReason[];
  colorClass: string;
  emptyText: string;
}) {
  const total = reasons.reduce((s, r) => s + r.count, 0);
  if (!reasons.length) return <p className="text-sm text-slate-500">{emptyText}</p>;
  return (
    <div className="space-y-2">
      {reasons.map((r) => (
        <HBar key={r.reason} reason={r.reason} count={r.count} total={total} colorClass={colorClass} />
      ))}
    </div>
  );
}

function QualityDistTable({ dist }: { dist: QualityDistributionEntry[] }) {
  const total = dist.reduce((s, d) => s + d.count, 0);
  return (
    <div className="space-y-2">
      {dist.map((d) => (
        <div key={d.category} className="flex items-center gap-3">
          <span className={`text-xs font-medium w-24 ${QUALITY_COLORS[d.category] ?? "text-slate-400"}`}>
            {d.category}
          </span>
          <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full"
              style={{ width: `${total > 0 ? (d.count / total) * 100 : 0}%` }}
            />
          </div>
          <span className="text-xs tabular-nums text-slate-400 w-8 text-right">{d.count}</span>
          <span className="text-xs tabular-nums text-slate-500 w-14 text-right">
            {d.avg_quality_score.toFixed(1)} avg
          </span>
        </div>
      ))}
    </div>
  );
}

function ComponentTable({ components }: { components: ComponentPerformance[] }) {
  if (!components.length) return <p className="text-sm text-slate-500">No component data</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
          <th className="pb-2 text-left">Component</th>
          <th className="pb-2 text-right">Winner Avg</th>
          <th className="pb-2 text-right">Loser Avg</th>
          <th className="pb-2 text-right">Edge Power</th>
          <th className="pb-2 text-right">Verdict</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-700/30">
        {components.map((c) => (
          <tr key={c.component} className="hover:bg-slate-700/20">
            <td className="py-2 font-medium text-slate-200">{c.component}</td>
            <td className="py-2 text-right tabular-nums text-emerald-400">
              {c.winner_avg != null ? c.winner_avg.toFixed(1) : "—"}
            </td>
            <td className="py-2 text-right tabular-nums text-red-400">
              {c.loser_avg != null ? c.loser_avg.toFixed(1) : "—"}
            </td>
            <td className="py-2 text-right tabular-nums text-slate-300">
              {c.discriminative_power != null ? c.discriminative_power.toFixed(2) : "—"}
            </td>
            <td className="py-2 text-right">
              <span className={`text-xs font-semibold ${VERDICT_COLORS[c.verdict] ?? "text-slate-400"}`}>
                {c.verdict.replace(/_/g, " ")}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function GateTable({ gates }: { gates: GateEntry[] }) {
  if (!gates.length) return <p className="text-sm text-slate-500">No gate data</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
          <th className="pb-2 text-left">Gate</th>
          <th className="pb-2 text-right">Passed</th>
          <th className="pb-2 text-right">Failed</th>
          <th className="pb-2 text-right">Pass Rate</th>
          <th className="pb-2 text-right">WR Passed</th>
          <th className="pb-2 text-right">Verdict</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-700/30">
        {gates.map((g) => (
          <tr key={g.gate_name} className="hover:bg-slate-700/20">
            <td className="py-2 font-medium text-slate-200">{g.gate_name.replace(/_/g, " ")}</td>
            <td className="py-2 text-right tabular-nums text-slate-400">{g.pass_count}</td>
            <td className="py-2 text-right tabular-nums text-slate-400">{g.fail_count}</td>
            <td className="py-2 text-right tabular-nums text-slate-300">
              {g.pass_rate_pct != null ? `${g.pass_rate_pct.toFixed(1)}%` : "—"}
            </td>
            <td className="py-2 text-right tabular-nums">
              {g.win_rate_when_passed != null ? (
                <span className={g.win_rate_when_passed >= 50 ? "text-emerald-400" : "text-red-400"}>
                  {g.win_rate_when_passed.toFixed(1)}%
                </span>
              ) : "—"}
            </td>
            <td className="py-2 text-right">
              <span className={`text-xs font-semibold ${VERDICT_COLORS[g.verdict] ?? "text-slate-400"}`}>
                {g.verdict.replace(/_/g, " ")}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function PostTradeView() {
  const [lookback, setLookback] = useState(30);
  const [tab, setTab] = useState<"attribution" | "journey" | "components" | "gates">("attribution");

  const summary = useAttributionSummary(lookback);
  const enrich = useAttributionEnrich();
  const journey = useEntryExitSummary(lookback);
  const components = useComponentPerformance(lookback);
  const gates = useGateEffectiveness(lookback);

  const s = summary.data;
  const j = journey.data;

  const tabs = [
    { id: "attribution", label: "Attribution" },
    { id: "journey",     label: "Trade Journey" },
    { id: "components",  label: "Components" },
    { id: "gates",       label: "Gates" },
  ] as const;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Post-Trade Intelligence</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Phase 20.5 — failure attribution, trade lifecycle, component power, gate effectiveness
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={lookback}
            onChange={(e) => setLookback(Number(e.target.value))}
            className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200"
          >
            {LOOKBACK_OPTIONS.map((d) => (
              <option key={d} value={d}>{d}d</option>
            ))}
          </select>
          <button
            onClick={() => enrich.mutate(200)}
            disabled={enrich.isPending}
            className="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600 disabled:opacity-50"
          >
            {enrich.isPending ? "Enriching…" : "Run Backfill"}
          </button>
        </div>
      </div>

      {/* Tabs */}
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

      {/* Attribution */}
      {tab === "attribution" && (
        <div className="space-y-5">
          {s && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard label="Completed" value={s.completed_trades} />
              <StatCard label="Attributed" value={s.attributed_trades} />
              <StatCard
                label="Coverage"
                value={`${s.attribution_coverage_pct.toFixed(1)}%`}
                sub="backfill if < 80%"
              />
              <StatCard label="Lookback" value={`${s.lookback_days}d`} />
            </div>
          )}

          {summary.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : s ? (
            <div className="grid gap-5 lg:grid-cols-2">
              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Top Failure Reasons
                </h2>
                <ReasonList
                  reasons={s.failure_reasons}
                  colorClass="bg-red-500"
                  emptyText="No attributed losses yet"
                />
              </div>

              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Top Success Reasons
                </h2>
                <ReasonList
                  reasons={s.success_reasons}
                  colorClass="bg-emerald-500"
                  emptyText="No attributed wins yet"
                />
              </div>

              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Model Failure Classes
                </h2>
                {s.model_failure_classes.length === 0 ? (
                  <p className="text-sm text-slate-500">No model failure data yet</p>
                ) : (
                  <div className="space-y-2">
                    {s.model_failure_classes.map((c) => {
                      const total = s.model_failure_classes.reduce((acc, x) => acc + x.count, 0);
                      return (
                        <div key={c.class} className="flex items-center gap-3">
                          <span className="text-xs text-slate-400 w-44 shrink-0">
                            {c.class.replace(/_/g, " ")}
                          </span>
                          <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full ${
                                c.class === "MODEL_FAILURE" ? "bg-red-500" :
                                c.class === "EXECUTION_FAILURE" ? "bg-amber-500" :
                                c.class === "MARKET_ANOMALY" ? "bg-purple-500" :
                                "bg-slate-500"
                              }`}
                              style={{ width: `${total > 0 ? (c.count / total) * 100 : 0}%` }}
                            />
                          </div>
                          <span className="text-xs tabular-nums text-slate-400 w-8 text-right">
                            {c.count}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  Signal Quality Distribution
                </h2>
                {s.quality_distribution.length === 0 ? (
                  <p className="text-sm text-slate-500">No quality data yet</p>
                ) : (
                  <QualityDistTable dist={s.quality_distribution} />
                )}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* Journey */}
      {tab === "journey" && (
        <div className="space-y-5">
          {journey.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : j ? (
            <>
              {/* MFE/MAE */}
              <div className="grid gap-5 lg:grid-cols-2">
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                  <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Winners — MFE / MAE / Time
                  </h2>
                  <div className="grid grid-cols-2 gap-3">
                    <StatCard
                      label="Avg MFE"
                      value={j.trade_journey.win_avg_mfe != null ? `${j.trade_journey.win_avg_mfe.toFixed(2)}%` : "—"}
                    />
                    <StatCard
                      label="Avg MAE"
                      value={j.trade_journey.win_avg_mae != null ? `${j.trade_journey.win_avg_mae.toFixed(2)}%` : "—"}
                    />
                    <StatCard
                      label="Avg Time to Target"
                      value={j.trade_journey.win_avg_time_to_target != null
                        ? `${j.trade_journey.win_avg_time_to_target.toFixed(0)}m`
                        : "—"}
                    />
                    <StatCard
                      label="P25–P75 Time"
                      value={
                        j.trade_journey.win_p25_time_to_target != null
                          ? `${j.trade_journey.win_p25_time_to_target}–${j.trade_journey.win_p75_time_to_target}m`
                          : "—"
                      }
                    />
                  </div>
                </div>

                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                  <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Losers — MFE / MAE / Time to Stop
                  </h2>
                  <div className="grid grid-cols-2 gap-3">
                    <StatCard
                      label="Avg MFE before Stop"
                      value={j.trade_journey.loss_avg_mfe != null ? `${j.trade_journey.loss_avg_mfe.toFixed(2)}%` : "—"}
                    />
                    <StatCard
                      label="Avg MAE"
                      value={j.trade_journey.loss_avg_mae != null ? `${j.trade_journey.loss_avg_mae.toFixed(2)}%` : "—"}
                    />
                    <StatCard
                      label="Avg Time to Stop"
                      value={j.trade_journey.loss_avg_time_to_stop != null
                        ? `${j.trade_journey.loss_avg_time_to_stop.toFixed(0)}m`
                        : "—"}
                    />
                    <StatCard
                      label="P25–P75 Time"
                      value={
                        j.trade_journey.loss_p25_time_to_stop != null
                          ? `${j.trade_journey.loss_p25_time_to_stop}–${j.trade_journey.loss_p75_time_to_stop}m`
                          : "—"
                      }
                    />
                  </div>
                </div>
              </div>

              {/* Stop distribution */}
              {j.stop_distribution?.buckets && (
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                  <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Stop Timing Distribution
                  </h2>
                  <div className="space-y-2">
                    {j.stop_distribution.buckets.map((b) => (
                      <div key={b.bucket} className="flex items-center gap-3">
                        <span className="text-xs text-slate-400 w-24 shrink-0">{b.bucket}</span>
                        <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-red-500 rounded-full"
                            style={{ width: `${b.pct}%` }}
                          />
                        </div>
                        <span className="text-xs tabular-nums text-slate-400 w-12 text-right">
                          {b.pct.toFixed(1)}% ({b.count})
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recovery */}
              {j.recovery_analysis && (
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                  <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                    Recovery Analysis (post stop-out)
                  </h2>
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <StatCard
                      label="Total Stopped"
                      value={j.recovery_analysis.total_stopped ?? "—"}
                    />
                    <StatCard
                      label="Would-Have-Recovered"
                      value={j.recovery_analysis.recovered_count ?? "—"}
                    />
                    <StatCard
                      label="Recovery Rate"
                      value={j.recovery_analysis.recovery_rate_pct != null
                        ? `${j.recovery_analysis.recovery_rate_pct.toFixed(1)}%`
                        : "—"}
                    />
                  </div>
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {/* Components */}
      {tab === "components" && (
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
          <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Component Discriminative Power
          </h2>
          {components.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            <div className="overflow-x-auto">
              <ComponentTable components={components.data?.component_performance ?? []} />
            </div>
          )}
        </div>
      )}

      {/* Gates */}
      {tab === "gates" && (
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
          <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Gate Effectiveness
          </h2>
          {gates.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            <div className="overflow-x-auto">
              <GateTable gates={gates.data?.gates ?? []} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
