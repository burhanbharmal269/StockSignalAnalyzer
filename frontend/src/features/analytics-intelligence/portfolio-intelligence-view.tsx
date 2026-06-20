"use client";

import { useState } from "react";
import {
  usePortfolioDashboard,
  usePortfolioHeat,
  useRiskOfRuin,
  useSuccessCriteria,
} from "@/hooks/use-analytics-intelligence";
import type { SuccessCriterion, CorrPair } from "@/services/analytics-intelligence.service";

const LOOKBACK_OPTIONS = [30, 60, 90] as const;

const STATUS_BG: Record<string, string> = {
  HEALTHY: "bg-emerald-500/15 border-emerald-500/30 text-emerald-400",
  NORMAL:  "bg-emerald-500/15 border-emerald-500/30 text-emerald-400",
  WARNING: "bg-amber-500/15 border-amber-500/30 text-amber-400",
  CRITICAL:"bg-red-500/15 border-red-500/30 text-red-400",
  ABNORMAL_DRAWDOWN: "bg-red-500/15 border-red-500/30 text-red-400",
  INSUFFICIENT_DATA: "bg-slate-700/50 border-slate-600/50 text-slate-400",
};

function StatCard({ label, value, sub, colorClass }: {
  label: string; value: string | number; sub?: string; colorClass?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-4">
      <p className="text-xs text-slate-400 uppercase tracking-wider">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${colorClass ?? "text-slate-100"}`}>
        {value}
      </p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-semibold ${STATUS_BG[status] ?? "bg-slate-700/50 border-slate-600/50 text-slate-400"}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function SCRow({ c }: { c: SuccessCriterion }) {
  return (
    <div className={`flex items-start justify-between gap-4 rounded-lg border px-4 py-3 ${
      c.passed
        ? "border-emerald-500/20 bg-emerald-500/5"
        : "border-red-500/20 bg-red-500/5"
    }`}>
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 text-lg leading-none ${c.passed ? "text-emerald-400" : "text-red-400"}`}>
          {c.passed ? "✓" : "✗"}
        </span>
        <div>
          <p className="text-sm font-medium text-slate-200">{c.id} — {c.description}</p>
          {c.note && <p className="mt-0.5 text-xs text-slate-500">{c.note}</p>}
        </div>
      </div>
      {c.value != null && (
        <div className="shrink-0 text-right">
          <p className={`text-sm font-semibold tabular-nums ${c.passed ? "text-emerald-400" : "text-red-400"}`}>
            {typeof c.value === "number" ? c.value.toFixed(2) : c.value}
          </p>
          {c.threshold != null && (
            <p className="text-xs text-slate-500">
              threshold: {typeof c.threshold === "number" ? c.threshold.toFixed(2) : c.threshold}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function CorrTable({ pairs }: { pairs: CorrPair[] }) {
  if (!pairs.length) return <p className="text-sm text-slate-500">No correlated pairs</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-700/60 text-xs text-slate-400 uppercase">
            <th className="pb-2 text-left">Pair</th>
            <th className="pb-2 text-right">Correlation</th>
            <th className="pb-2 text-right">Level</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/30">
          {pairs.map((p) => (
            <tr key={`${p.symbol_a}-${p.symbol_b}`} className="hover:bg-slate-700/20">
              <td className="py-2 font-medium text-slate-200">
                {p.symbol_a} / {p.symbol_b}
              </td>
              <td className="py-2 text-right tabular-nums">
                <span className={Math.abs(p.correlation) >= 0.7 ? "text-red-400" : "text-amber-400"}>
                  {p.correlation.toFixed(3)}
                </span>
              </td>
              <td className="py-2 text-right">
                <StatusBadge status={p.level} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PortfolioIntelligenceView() {
  const [lookback, setLookback] = useState(30);
  const [tab, setTab] = useState<"overview" | "risk" | "criteria" | "correlation">("overview");

  const dashboard = usePortfolioDashboard();
  const heat = usePortfolioHeat();
  const ror = useRiskOfRuin(lookback);
  const sc = useSuccessCriteria(lookback);

  const d = dashboard.data;
  const hd = heat.data;

  const tabs = [
    { id: "overview",    label: "Overview" },
    { id: "risk",        label: "Risk of Ruin" },
    { id: "criteria",    label: "Success Criteria" },
    { id: "correlation", label: "Correlation" },
  ] as const;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Portfolio Intelligence</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Phase 19 — correlation risk, sector exposure, heat, drawdown, and institutional readiness
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
          {d && (
            <StatusBadge status={d.overall_status} />
          )}
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

      {/* Overview */}
      {tab === "overview" && (
        <div className="space-y-5">
          {/* Portfolio heat */}
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Portfolio Heat (Live)
            </h2>
            {heat.isLoading ? (
              <p className="text-sm text-slate-500">Loading…</p>
            ) : hd ? (
              <>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-4">
                  <StatCard
                    label="Heat"
                    value={`${hd.heat_pct.toFixed(1)}%`}
                    sub="of daily budget"
                    colorClass={
                      hd.status === "CRITICAL" ? "text-red-400" :
                      hd.status === "WARNING"  ? "text-amber-400" :
                      "text-emerald-400"
                    }
                  />
                  <StatCard label="Open Positions" value={hd.open_positions} />
                  <StatCard label="Wins Today" value={hd.wins_today} colorClass="text-emerald-400" />
                  <StatCard label="Losses Today" value={hd.losses_today} colorClass="text-red-400" />
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      hd.status === "CRITICAL" ? "bg-red-500" :
                      hd.status === "WARNING"  ? "bg-amber-500" :
                      "bg-emerald-500"
                    }`}
                    style={{ width: `${Math.min(hd.heat_pct, 100)}%` }}
                  />
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-xs text-slate-500">0%</span>
                  <span className="text-xs text-amber-400">Warning {hd.thresholds.warning}%</span>
                  <span className="text-xs text-red-400">Critical {hd.thresholds.critical}%</span>
                </div>
              </>
            ) : null}
          </div>

          {/* Sector exposure */}
          {d?.sector_exposure?.sectors && (
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
              <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Sector Exposure
              </h2>
              <div className="space-y-2">
                {d.sector_exposure.sectors.map((s) => (
                  <div key={s.sector} className="flex items-center gap-3">
                    <span className="w-28 text-xs text-slate-400 shrink-0 truncate">{s.sector}</span>
                    <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          s.status === "CRITICAL" ? "bg-red-500" :
                          s.status === "WARNING"  ? "bg-amber-500" :
                          "bg-blue-500"
                        }`}
                        style={{ width: `${Math.min(s.pct, 100)}%` }}
                      />
                    </div>
                    <span className="text-xs tabular-nums text-slate-400 w-12 text-right">
                      {s.pct.toFixed(1)}%
                    </span>
                    {s.status !== "OK" && <StatusBadge status={s.status} />}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Risk of Ruin */}
      {tab === "risk" && (
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
          <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Risk of Ruin / Drawdown Monitor
          </h2>
          {ror.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : ror.data ? (
            <>
              <div className="mb-4 flex items-center gap-3">
                <StatusBadge status={ror.data.status} />
                {ror.data.alert && (
                  <span className="text-sm text-red-400">{ror.data.alert}</span>
                )}
              </div>
              {ror.data.status === "INSUFFICIENT_DATA" ? (
                <p className="text-sm text-slate-500">
                  Need {ror.data.days_needed} days with settled trades — have {ror.data.days_have} so far.
                </p>
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <StatCard
                    label="Current Drawdown"
                    value={`${((ror.data.current_drawdown ?? 0) * 100).toFixed(3)}%`}
                    colorClass={
                      ror.data.status === "ABNORMAL_DRAWDOWN" ? "text-red-400" : "text-slate-100"
                    }
                  />
                  <StatCard
                    label="Avg Historical DD"
                    value={`${((ror.data.avg_historical_drawdown ?? 0) * 100).toFixed(3)}%`}
                    sub={`${lookback}d window`}
                  />
                  <StatCard
                    label="Multiplier"
                    value={`${ror.data.multiplier}×`}
                    sub="alert threshold"
                  />
                  <StatCard
                    label="Abnormal Threshold"
                    value={`${((ror.data.abnormal_threshold ?? 0) * 100).toFixed(3)}%`}
                    sub="= avg × multiplier"
                  />
                  <StatCard
                    label="Days in Sample"
                    value={ror.data.days_in_sample ?? "—"}
                  />
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {/* Success Criteria */}
      {tab === "criteria" && (
        <div className="space-y-4">
          {sc.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : sc.data ? (
            <>
              <div className="flex items-center gap-4">
                <StatusBadge status={sc.data.all_conditions_met ? "HEALTHY" : "WARNING"} />
                <span className="text-sm text-slate-400">
                  {sc.data.passed_count}/{sc.data.total_count} conditions met
                </span>
              </div>
              <div className="space-y-2">
                {(sc.data.conditions ?? []).map((c) => (
                  <SCRow key={c.id} c={c} />
                ))}
              </div>
            </>
          ) : null}
        </div>
      )}

      {/* Correlation */}
      {tab === "correlation" && (
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
          <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            Pairwise P&L Correlation
          </h2>
          {dashboard.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : d?.correlation ? (
            <>
              {d.correlation.alert && (
                <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-400">
                  {d.correlation.alert}
                </div>
              )}
              {d.correlation.status === "INSUFFICIENT_DATA" ? (
                <p className="text-sm text-slate-500">
                  Need at least 2 symbols with settled trades ({d.correlation.symbol_count} available).
                </p>
              ) : (
                <CorrTable pairs={d.correlation.pairs ?? []} />
              )}
            </>
          ) : null}
        </div>
      )}
    </div>
  );
}
