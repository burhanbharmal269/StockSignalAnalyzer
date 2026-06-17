"use client";

import { useState } from "react";
import {
  useSignalSummary,
  useStrategyLeaderboard,
  useFilterAnalytics,
  useRegimePerformance,
  useLeaderboard,
  useInsights,
  useOutcomeCheck,
} from "@/hooks/use-signal-intelligence";
import type { Insight, LeaderboardEntry, RegimeStrategyMetric } from "@/services/signal-intelligence.service";

const LOOKBACK_OPTIONS = [7, 14, 30, 90] as const;

const PRIORITY_STYLES: Record<string, string> = {
  HIGH: "bg-red-500/15 text-red-400 border-red-500/30",
  MEDIUM: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  LOW: "bg-blue-500/15 text-blue-400 border-blue-500/30",
};

const VERDICT_STYLES: Record<string, string> = {
  IMPROVING: "text-emerald-400",
  HURTING: "text-red-400",
  NEUTRAL: "text-slate-400",
  INSUFFICIENT_DATA: "text-slate-500",
};

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string | number;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-4">
      <p className="text-xs text-slate-400 uppercase tracking-wider">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-100">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function InsightCard({ insight }: { insight: Insight }) {
  return (
    <div
      className={`rounded-lg border px-4 py-3 ${PRIORITY_STYLES[insight.priority] ?? "border-slate-700/60 bg-slate-800/50 text-slate-300"}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <span className="text-xs font-medium uppercase opacity-70">
            {insight.priority} · {insight.category}
          </span>
          <p className="mt-0.5 font-medium">{insight.title}</p>
          <p className="mt-1 text-xs opacity-80 leading-relaxed">{insight.description}</p>
        </div>
        {insight.metric_value != null && (
          <div className="flex-shrink-0 text-right">
            <p className="text-lg font-semibold">{insight.metric_value}</p>
            {insight.metric_label && (
              <p className="text-xs opacity-60">{insight.metric_label}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function LeaderboardTable({
  entries,
  nameLabel,
}: {
  entries: LeaderboardEntry[];
  nameLabel: string;
}) {
  if (!entries.length) {
    return <p className="text-sm text-slate-500 py-4 text-center">Insufficient data</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
            <th className="pb-2 text-left w-8">#</th>
            <th className="pb-2 text-left">{nameLabel}</th>
            <th className="pb-2 text-right">Signals</th>
            <th className="pb-2 text-right">Win %</th>
            <th className="pb-2 text-right">PF</th>
            <th className="pb-2 text-right">Expectancy</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/30">
          {entries.map((e) => (
            <tr key={`${e.rank}-${e.name}`} className="hover:bg-slate-700/20">
              <td className="py-2 text-slate-500">{e.rank}</td>
              <td className="py-2 font-medium text-slate-200">{e.name}</td>
              <td className="py-2 text-right text-slate-400">{e.signal_count}</td>
              <td className="py-2 text-right">
                <span className={e.win_rate >= 55 ? "text-emerald-400" : e.win_rate >= 45 ? "text-slate-300" : "text-red-400"}>
                  {e.win_rate.toFixed(1)}%
                </span>
              </td>
              <td className="py-2 text-right text-slate-300">{e.profit_factor.toFixed(2)}x</td>
              <td className="py-2 text-right">
                <span className={e.expectancy >= 0 ? "text-emerald-400" : "text-red-400"}>
                  {e.expectancy.toFixed(3)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RegimeMatrix({ metrics }: { metrics: RegimeStrategyMetric[] }) {
  if (!metrics.length) {
    return <p className="text-sm text-slate-500 py-4 text-center">Insufficient data — need settled signals</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
            <th className="pb-2 text-left">Regime</th>
            <th className="pb-2 text-left">Strategy</th>
            <th className="pb-2 text-right">Signals</th>
            <th className="pb-2 text-right">Win %</th>
            <th className="pb-2 text-right">PF</th>
            <th className="pb-2 text-right">Expectancy</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/30">
          {metrics.map((m, i) => (
            <tr key={i} className="hover:bg-slate-700/20">
              <td className="py-2 text-slate-300 font-mono text-xs">{m.regime}</td>
              <td className="py-2 text-slate-200">{m.strategy_type}</td>
              <td className="py-2 text-right text-slate-400">{m.signal_count}</td>
              <td className="py-2 text-right">
                <span className={m.win_rate >= 55 ? "text-emerald-400" : m.win_rate >= 45 ? "text-slate-300" : "text-red-400"}>
                  {m.win_rate.toFixed(1)}%
                </span>
              </td>
              <td className="py-2 text-right text-slate-300">{m.profit_factor.toFixed(2)}x</td>
              <td className="py-2 text-right">
                <span className={m.expectancy >= 0 ? "text-emerald-400" : "text-red-400"}>
                  {m.expectancy.toFixed(3)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SignalIntelligenceView() {
  const [lookback, setLookback] = useState<number>(30);
  const [activeTab, setActiveTab] = useState<"overview" | "regime" | "leaderboard" | "filters" | "insights">("overview");

  const summary = useSignalSummary();
  const strategies = useStrategyLeaderboard(lookback);
  const filters = useFilterAnalytics(lookback);
  const regime = useRegimePerformance(lookback);
  const leaderboard = useLeaderboard(lookback);
  const insights = useInsights(lookback);
  const outcomeCheck = useOutcomeCheck();

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "regime", label: "Regime Matrix" },
    { id: "leaderboard", label: "Leaderboard" },
    { id: "filters", label: "Filters" },
    { id: "insights", label: "Insights" },
  ] as const;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Signal Intelligence</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Performance analytics derived from signal outcomes — no executed trades required
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={lookback}
            onChange={(e) => setLookback(Number(e.target.value))}
            className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200"
          >
            {LOOKBACK_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {d}d
              </option>
            ))}
          </select>
          <button
            onClick={() => outcomeCheck.mutate()}
            disabled={outcomeCheck.isPending}
            className="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600 disabled:opacity-50"
          >
            {outcomeCheck.isPending ? "Running…" : "Run Outcome Check"}
          </button>
        </div>
      </div>

      {/* Summary stats */}
      {summary.data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
          <StatCard label="Total Today" value={summary.data.total} />
          <StatCard label="Accepted" value={summary.data.accepted} />
          <StatCard label="Rejected" value={summary.data.rejected} />
          <StatCard label="Symbols" value={summary.data.unique_symbols} />
          <StatCard label="Strategies" value={summary.data.strategies_active} />
          <StatCard
            label="Avg Score"
            value={summary.data.avg_score.toFixed(1)}
            sub="of 100"
          />
          <StatCard
            label="Avg Confidence"
            value={`${summary.data.avg_confidence.toFixed(1)}%`}
          />
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-slate-700/60">
        <nav className="flex gap-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`border-b-2 pb-2 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? "border-blue-500 text-blue-400"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}

      {activeTab === "overview" && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Best strategies */}
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">
              Top Strategies
            </h2>
            {strategies.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : strategies.data?.strategies.length ? (
              <div className="space-y-3">
                {strategies.data.strategies.slice(0, 5).map((s) => (
                  <div key={s.strategy_type} className="flex items-center justify-between">
                    <div>
                      <span className="text-sm font-medium text-slate-200">{s.strategy_type}</span>
                      <span className="ml-2 text-xs text-slate-500">{s.accepted_count} signals</span>
                    </div>
                    <div className="flex gap-4 text-sm">
                      <span className={s.win_rate >= 55 ? "text-emerald-400" : "text-slate-400"}>
                        {s.win_rate.toFixed(1)}% WR
                      </span>
                      <span className="text-slate-400">PF {s.profit_factor.toFixed(2)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No data — run an outcome check to populate</p>
            )}
          </div>

          {/* Insights preview */}
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">
              Top Insights
            </h2>
            {insights.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : insights.data?.insights.length ? (
              <div className="space-y-3">
                {insights.data.insights.slice(0, 3).map((ins, i) => (
                  <InsightCard key={i} insight={ins} />
                ))}
                {insights.data.insights.length > 3 && (
                  <button
                    onClick={() => setActiveTab("insights")}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    +{insights.data.insights.length - 3} more insights →
                  </button>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-500">No insights yet — need more settled signals</p>
            )}
          </div>

          {/* Best per regime */}
          {regime.data && Object.keys(regime.data.best_per_regime).length > 0 && (
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
              <h2 className="mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">
                Best Strategy Per Regime
              </h2>
              <div className="space-y-2">
                {Object.entries(regime.data.best_per_regime).map(([regime, strategy]) => (
                  <div key={regime} className="flex items-center justify-between">
                    <span className="text-sm font-mono text-slate-400">{regime}</span>
                    <span className="text-sm font-medium text-emerald-400">{strategy}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top symbols */}
          {leaderboard.data?.symbols.length ? (
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
              <h2 className="mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">
                Top Symbols
              </h2>
              <LeaderboardTable entries={leaderboard.data.symbols.slice(0, 8)} nameLabel="Symbol" />
            </div>
          ) : null}
        </div>
      )}

      {activeTab === "regime" && (
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
              Strategy × Regime Performance Matrix
            </h2>
            {regime.data && Object.keys(regime.data.best_per_regime).length > 0 && (
              <div className="flex gap-3 flex-wrap">
                {Object.entries(regime.data.best_per_regime).map(([r, s]) => (
                  <span key={r} className="text-xs bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 rounded px-2 py-0.5">
                    {r}: {s}
                  </span>
                ))}
              </div>
            )}
          </div>
          {regime.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            <RegimeMatrix metrics={regime.data?.metrics ?? []} />
          )}
        </div>
      )}

      {activeTab === "leaderboard" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">Symbols</h2>
            {leaderboard.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : (
              <LeaderboardTable entries={leaderboard.data?.symbols ?? []} nameLabel="Symbol" />
            )}
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">Sectors</h2>
            {leaderboard.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : (
              <LeaderboardTable entries={leaderboard.data?.sectors ?? []} nameLabel="Sector" />
            )}
          </div>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">Regimes</h2>
            {leaderboard.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : (
              <LeaderboardTable entries={leaderboard.data?.regimes ?? []} nameLabel="Regime" />
            )}
          </div>
        </div>
      )}

      {activeTab === "filters" && (
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">
            Filter Effectiveness
          </h2>
          {filters.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : !filters.data?.filters.length ? (
            <p className="text-sm text-slate-500 py-4 text-center">No filter data — need settled signal outcomes</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
                    <th className="pb-2 text-left">Filter</th>
                    <th className="pb-2 text-right">Before</th>
                    <th className="pb-2 text-right">After</th>
                    <th className="pb-2 text-right">Pass Rate</th>
                    <th className="pb-2 text-right">WR Passed</th>
                    <th className="pb-2 text-right">WR Rejected</th>
                    <th className="pb-2 text-right">Delta</th>
                    <th className="pb-2 text-right">Verdict</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30">
                  {filters.data.filters.map((f) => (
                    <tr key={f.filter_name} className="hover:bg-slate-700/20">
                      <td className="py-2">
                        <p className="font-medium text-slate-200">{f.filter_name}</p>
                        <p className="text-xs text-slate-500">{f.description}</p>
                      </td>
                      <td className="py-2 text-right text-slate-400">{f.signals_before}</td>
                      <td className="py-2 text-right text-slate-400">{f.signals_after}</td>
                      <td className="py-2 text-right text-slate-300">{f.pass_rate_pct.toFixed(1)}%</td>
                      <td className="py-2 text-right text-slate-300">
                        {f.win_rate_passed != null ? `${f.win_rate_passed.toFixed(1)}%` : "—"}
                      </td>
                      <td className="py-2 text-right text-slate-300">
                        {f.win_rate_rejected != null ? `${f.win_rate_rejected.toFixed(1)}%` : "—"}
                      </td>
                      <td className="py-2 text-right">
                        <span className={f.performance_delta >= 0 ? "text-emerald-400" : "text-red-400"}>
                          {f.performance_delta >= 0 ? "+" : ""}{f.performance_delta.toFixed(1)}%
                        </span>
                      </td>
                      <td className="py-2 text-right">
                        <span className={`text-xs font-semibold ${VERDICT_STYLES[f.verdict] ?? "text-slate-400"}`}>
                          {f.verdict.replace("_", " ")}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === "insights" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
              Optimization Insights
            </h2>
            {insights.data && (
              <p className="text-xs text-slate-500">
                {insights.data.insight_count} recommendations • {lookback}d window
              </p>
            )}
          </div>
          {insights.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : !insights.data?.insights.length ? (
            <p className="text-sm text-slate-500 py-8 text-center">
              No insights yet — run more signals and outcome checks to generate recommendations
            </p>
          ) : (
            <div className="space-y-3">
              {insights.data.insights.map((ins, i) => (
                <InsightCard key={i} insight={ins} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
