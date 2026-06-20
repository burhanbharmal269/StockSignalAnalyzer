"use client";

import { useState } from "react";
import { useWeeklyReport } from "@/hooks/use-analytics-intelligence";

const LOOKBACK_OPTIONS = [7, 14, 30] as const;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
      <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">{title}</h2>
      {children}
    </div>
  );
}

function HBar({ label, count, total, colorClass = "bg-blue-500" }: {
  label: string; count: number; total: number; colorClass?: string;
}) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-slate-400 w-52 shrink-0 truncate" title={label}>
        {label.replace(/_/g, " ")}
      </span>
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-slate-400 w-8 text-right">{count}</span>
    </div>
  );
}

export default function WeeklyReportView() {
  const [lookback, setLookback] = useState(7);
  const report = useWeeklyReport(lookback);
  const d = report.data;

  const failTotal = d?.top_failure_reasons?.reduce((s, r) => s + r.count, 0) ?? 0;
  const succTotal = d?.top_success_reasons?.reduce((s, r) => s + r.count, 0) ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Weekly Intelligence Report</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Phase 20.5 — 12-section post-trade intelligence digest
          </p>
        </div>
        <select
          value={lookback}
          onChange={(e) => setLookback(Number(e.target.value))}
          className="rounded border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-slate-200"
        >
          {LOOKBACK_OPTIONS.map((v) => (
            <option key={v} value={v}>{v}d</option>
          ))}
        </select>
      </div>

      {report.isLoading && <p className="text-sm text-slate-500">Generating report…</p>}

      {d?.error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {d.error}
        </div>
      )}

      {d && !d.error && (
        <>
          {/* Alerts */}
          {d.alerts && d.alerts.length > 0 && (
            <div className="space-y-2">
              {d.alerts.map((a, i) => (
                <div key={i} className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-400">
                  {a}
                </div>
              ))}
            </div>
          )}

          <div className="grid gap-5 lg:grid-cols-2">
            {/* S1 — Failure reasons */}
            <Section title="Top Failure Reasons">
              {!d.top_failure_reasons?.length ? (
                <p className="text-sm text-slate-500">No attributed losses in window</p>
              ) : (
                <div className="space-y-2">
                  {d.top_failure_reasons.map((r) => (
                    <HBar key={r.reason} label={r.reason} count={r.count} total={failTotal} colorClass="bg-red-500" />
                  ))}
                </div>
              )}
            </Section>

            {/* S2 — Success reasons */}
            <Section title="Top Success Reasons">
              {!d.top_success_reasons?.length ? (
                <p className="text-sm text-slate-500">No attributed wins in window</p>
              ) : (
                <div className="space-y-2">
                  {d.top_success_reasons.map((r) => (
                    <HBar key={r.reason} label={r.reason} count={r.count} total={succTotal} colorClass="bg-emerald-500" />
                  ))}
                </div>
              )}
            </Section>

            {/* S3 — Model failure classes */}
            <Section title="Model Failure Rate">
              {!d.model_failure_rate || Object.keys(d.model_failure_rate).length === 0 ? (
                <p className="text-sm text-slate-500">No data</p>
              ) : (
                <div className="space-y-2">
                  {Object.entries(d.model_failure_rate).map(([cls, count]) => {
                    const total = Object.values(d.model_failure_rate!).reduce((s, n) => s + n, 0);
                    return (
                      <HBar
                        key={cls}
                        label={cls}
                        count={count}
                        total={total}
                        colorClass={
                          cls === "MODEL_FAILURE" ? "bg-red-500" :
                          cls === "EXECUTION_FAILURE" ? "bg-amber-500" :
                          cls === "MARKET_ANOMALY" ? "bg-purple-500" :
                          "bg-slate-500"
                        }
                      />
                    );
                  })}
                </div>
              )}
            </Section>

            {/* MFE/MAE summary */}
            <Section title="MFE / MAE Summary">
              {!d.mfe_mae_summary ? (
                <p className="text-sm text-slate-500">No data</p>
              ) : (
                <div className="grid grid-cols-2 gap-3">
                  {[
                    { label: "Winner Avg MFE", val: d.mfe_mae_summary.win_avg_mfe, color: "text-emerald-400" },
                    { label: "Winner Avg MAE", val: d.mfe_mae_summary.win_avg_mae, color: "text-slate-300" },
                    { label: "Loser Avg MFE",  val: d.mfe_mae_summary.loss_avg_mfe, color: "text-slate-300" },
                    { label: "Loser Avg MAE",  val: d.mfe_mae_summary.loss_avg_mae, color: "text-red-400" },
                  ].map(({ label, val, color }) => (
                    <div key={label} className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-3">
                      <p className="text-xs text-slate-500 uppercase tracking-wider">{label}</p>
                      <p className={`mt-1 text-xl font-semibold tabular-nums ${color}`}>
                        {val != null ? `${val.toFixed(2)}%` : "—"}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            {/* Signal quality distribution */}
            <Section title="Signal Quality Distribution">
              {!d.signal_quality_distribution?.length ? (
                <p className="text-sm text-slate-500">No quality data</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
                        <th className="pb-2 text-left">Category</th>
                        <th className="pb-2 text-right">Count</th>
                        <th className="pb-2 text-right">Avg Score</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/30">
                      {d.signal_quality_distribution.map((q) => (
                        <tr key={q.category} className="hover:bg-slate-700/20">
                          <td className="py-2 text-slate-200">{q.category}</td>
                          <td className="py-2 text-right tabular-nums text-slate-400">{q.count}</td>
                          <td className="py-2 text-right tabular-nums text-slate-300">
                            {q.avg_score != null ? q.avg_score.toFixed(1) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>

            {/* Regime ranking */}
            <Section title="Regime Performance">
              {!d.regime_ranking?.length ? (
                <p className="text-sm text-slate-500">No regime data</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
                        <th className="pb-2 text-left">Regime</th>
                        <th className="pb-2 text-right">n</th>
                        <th className="pb-2 text-right">Win %</th>
                        <th className="pb-2 text-right">PF</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/30">
                      {d.regime_ranking.map((r) => (
                        <tr key={r.regime} className="hover:bg-slate-700/20">
                          <td className="py-2 font-mono text-xs text-slate-300">{r.regime}</td>
                          <td className="py-2 text-right tabular-nums text-slate-400">{r.count ?? "—"}</td>
                          <td className="py-2 text-right tabular-nums">
                            {r.win_rate != null ? (
                              <span className={r.win_rate >= 50 ? "text-emerald-400" : "text-red-400"}>
                                {r.win_rate.toFixed(1)}%
                              </span>
                            ) : "—"}
                          </td>
                          <td className="py-2 text-right tabular-nums text-slate-300">
                            {r.profit_factor != null ? `${r.profit_factor.toFixed(2)}×` : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Section>

            {/* Component ranking */}
            {d.component_ranking && d.component_ranking.length > 0 && (
              <Section title="Component Discriminative Ranking">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
                        <th className="pb-2 text-left">Component</th>
                        <th className="pb-2 text-right">Edge Power</th>
                        <th className="pb-2 text-right">Verdict</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/30">
                      {d.component_ranking.map((c) => (
                        <tr key={c.component} className="hover:bg-slate-700/20">
                          <td className="py-2 text-slate-200">{c.component}</td>
                          <td className="py-2 text-right tabular-nums text-slate-300">
                            {c.discriminative_power != null ? c.discriminative_power.toFixed(2) : "—"}
                          </td>
                          <td className="py-2 text-right">
                            <span className={`text-xs font-semibold ${
                              c.verdict === "STRONG" ? "text-emerald-400" :
                              c.verdict === "WEAK"   ? "text-red-400" :
                              "text-slate-400"
                            }`}>
                              {c.verdict ?? "—"}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>
            )}

            {/* Time window ranking */}
            {d.time_window_ranking && d.time_window_ranking.length > 0 && (
              <Section title="Best Entry Time Windows (IST)">
                <div className="space-y-2">
                  {d.time_window_ranking.map((w) => (
                    <div key={w.window} className="flex items-center justify-between">
                      <span className="text-sm font-mono text-slate-300">{w.window}</span>
                      <div className="flex gap-4 text-sm">
                        <span className={w.win_rate != null && w.win_rate >= 50 ? "text-emerald-400" : "text-slate-400"}>
                          {w.win_rate != null ? `${w.win_rate.toFixed(1)}% WR` : "—"}
                        </span>
                        <span className="text-slate-500">{w.count ?? 0} signals</span>
                      </div>
                    </div>
                  ))}
                </div>
              </Section>
            )}
          </div>

          <p className="text-xs text-slate-600 text-right">
            Generated at: {new Date(d.generated_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST
          </p>
        </>
      )}
    </div>
  );
}
