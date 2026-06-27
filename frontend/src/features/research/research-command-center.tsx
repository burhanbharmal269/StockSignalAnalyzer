"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { researchService } from "@/services/research.service";
import type { CohortStat, LvpDriftCheck, Recommendation, StrategyHealth } from "@/types";

// ── Palette helpers ───────────────────────────────────────────────────────────

function pct(v: number | null | undefined, d = 1) {
  return v == null ? "—" : `${v.toFixed(d)}%`;
}
function num(v: number | null | undefined, d = 2) {
  return v == null ? "—" : v.toFixed(d);
}
function clamp(v: number, lo = 0, hi = 100) {
  return Math.max(lo, Math.min(hi, v));
}

/* Score → traffic-light color classes */
function scoreTextCls(s: number) {
  if (s >= 75) return "text-emerald-400";
  if (s >= 50) return "text-amber-400";
  return "text-rose-400";
}
function scoreBarCls(s: number) {
  if (s >= 75) return "bg-emerald-500";
  if (s >= 50) return "bg-amber-500";
  return "bg-rose-500";
}

/* Win-rate → colored text */
function wrCls(wr: number) {
  if (wr >= 55) return "text-emerald-400 font-semibold";
  if (wr >= 50) return "text-emerald-600 font-medium";
  if (wr >= 45) return "text-amber-400";
  return "text-rose-400";
}

/* Profit-factor → colored text */
function pfCls(pf: number | null | undefined) {
  if (pf == null) return "";
  if (pf >= 1.5) return "text-emerald-400 font-semibold";
  if (pf >= 1.0) return "text-emerald-600";
  return "text-rose-400";
}

/* Expectancy → color */
function expCls(e: number | null | undefined) {
  if (e == null) return "";
  return e >= 0 ? "text-sky-400" : "text-rose-400";
}

function TrendBadge({ t }: { t: "IMPROVING" | "STABLE" | "DECLINING" }) {
  const cls = {
    IMPROVING: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
    STABLE:    "bg-slate-500/15 text-slate-300 border border-slate-500/30",
    DECLINING: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  }[t];
  return (
    <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold tracking-wide ${cls}`}>
      {t === "IMPROVING" ? "▲ " : t === "DECLINING" ? "▼ " : "— "}
      {t}
    </span>
  );
}

function StatusBadge({ s }: { s: Recommendation["status"] }) {
  const map: Record<string, string> = {
    READY_FOR_REVIEW: "bg-sky-500/20 text-sky-300 border border-sky-500/40",
    EMERGING:         "bg-amber-500/20 text-amber-300 border border-amber-500/40",
    WAIT:             "bg-slate-500/15 text-slate-400 border border-slate-500/30",
    INSUFFICIENT_DATA:"bg-slate-700/40 text-slate-500 border border-slate-600/30",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${map[s] ?? map.WAIT}`}>
      {s.replace(/_/g, " ")}
    </span>
  );
}

// ── Health score arc ──────────────────────────────────────────────────────────

function ScoreRing({ score }: { score: number }) {
  const s = clamp(score);
  const r = 36;
  const circ = 2 * Math.PI * r;
  const filled = (s / 100) * circ;
  const stroke = s >= 75 ? "#34d399" : s >= 50 ? "#fbbf24" : "#f87171";

  return (
    <div className="relative flex items-center justify-center w-28 h-28">
      <svg className="absolute inset-0 -rotate-90" width="112" height="112" viewBox="0 0 112 112">
        <circle cx="56" cy="56" r={r} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="8" />
        <circle
          cx="56" cy="56" r={r}
          fill="none"
          stroke={stroke}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circ - filled}`}
          style={{ transition: "stroke-dasharray 0.6s ease" }}
        />
      </svg>
      <div className="text-center z-10">
        <div className={`text-3xl font-bold tabular-nums leading-none ${scoreTextCls(s)}`}>
          {s.toFixed(0)}
        </div>
        <div className="text-[10px] text-slate-500 mt-0.5">/ 100</div>
      </div>
    </div>
  );
}

// ── Health card ───────────────────────────────────────────────────────────────

function HealthCard({ health }: { health: StrategyHealth }) {
  const cats = Object.entries(health.categories || {});
  return (
    <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-5 space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="font-semibold text-white text-base tracking-tight">Platform Health</h2>
          <p className="text-xs text-slate-500 mt-0.5">8-category weighted score</p>
        </div>
        <TrendBadge t={health.trend} />
      </div>

      <div className="flex gap-6 items-center">
        <ScoreRing score={health.overall} />
        <div className="flex-1 space-y-2.5">
          {cats.map(([key, cat]) => {
            const s = clamp(cat.score);
            return (
              <div key={key} className="space-y-0.5">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-400 capitalize">{key.replace(/_/g, " ")}</span>
                  <span className={`tabular-nums font-semibold ${scoreTextCls(s)}`}>{s.toFixed(0)}</span>
                </div>
                <div className="h-1 rounded-full bg-slate-700/60">
                  <div
                    className={`h-1 rounded-full transition-all ${scoreBarCls(s)}`}
                    style={{ width: `${s}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <p className="text-[11px] text-slate-600">
        Evaluated {new Date(health.evaluated_at).toLocaleTimeString()}
      </p>
    </div>
  );
}

// ── Cohort table ──────────────────────────────────────────────────────────────

function CohortTable({ title, rows }: { title: string; rows: CohortStat[] }) {
  return (
    <div className="space-y-2">
      <h3 className="text-[11px] font-bold text-slate-500 uppercase tracking-widest">{title}</h3>
      {rows.length === 0 ? (
        <p className="text-xs text-slate-600 italic py-2">Not enough data yet (min 5 trades)</p>
      ) : (
        <table className="text-xs w-full">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="text-left py-1.5 pr-3 text-slate-500 font-medium">Cohort</th>
              <th className="text-right py-1.5 pr-3 text-slate-500 font-medium">n</th>
              <th className="text-right py-1.5 pr-3 text-slate-500 font-medium">Win%</th>
              <th className="text-right py-1.5 pr-3 text-slate-500 font-medium">PF</th>
              <th className="text-right py-1.5 text-slate-500 font-medium">Exp</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={r.cohort}
                className={`border-b border-slate-800/50 last:border-0 ${i % 2 === 0 ? "bg-slate-800/20" : ""}`}
              >
                <td className="py-1.5 pr-3 text-slate-200 font-medium max-w-[140px] truncate" title={r.cohort}>
                  {r.cohort}
                </td>
                <td className="text-right py-1.5 pr-3 tabular-nums text-slate-400">{r.trade_count}</td>
                <td className={`text-right py-1.5 pr-3 tabular-nums ${wrCls(r.win_rate)}`}>
                  {pct(r.win_rate)}
                </td>
                <td className={`text-right py-1.5 pr-3 tabular-nums ${pfCls(r.profit_factor)}`}>
                  {num(r.profit_factor)}×
                </td>
                <td className={`text-right py-1.5 tabular-nums ${expCls(r.expectancy)}`}>
                  {num(r.expectancy, 4)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Recommendation card ───────────────────────────────────────────────────────

function RecCard({ rec }: { rec: Recommendation }) {
  const [open, setOpen] = useState(false);
  const out = rec.direction === "OUTPERFORMING";

  return (
    <div className={`border rounded-lg overflow-hidden ${out ? "border-emerald-800/50" : "border-rose-800/50"}`}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 p-3 hover:bg-slate-800/40 transition-colors text-left"
      >
        <span
          className={`text-base font-bold w-5 text-center shrink-0 ${out ? "text-emerald-400" : "text-rose-400"}`}
        >
          {out ? "↑" : "↓"}
        </span>
        <div className="flex-1 min-w-0 space-y-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-sm text-white">{rec.dimension}</span>
            {rec.cohort_key && (
              <span className="text-xs text-slate-400">→ {rec.cohort_key}</span>
            )}
            <StatusBadge s={rec.status} />
          </div>
          <div className="text-xs text-slate-500">
            n={rec.trade_count}
            &nbsp;·&nbsp;WR{" "}
            <span className={wrCls(rec.cohort_win_rate ?? 0)}>{pct(rec.cohort_win_rate)}</span>
            &nbsp;vs&nbsp;
            <span className="text-slate-400">{pct(rec.baseline_win_rate)}</span>
            {rec.z_statistic != null && (
              <>&nbsp;·&nbsp;z=<span className="text-sky-400">{rec.z_statistic.toFixed(2)}</span></>
            )}
          </div>
        </div>
        <span className="text-slate-600 text-xs shrink-0">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t border-slate-700/50 p-3 bg-slate-900/60 space-y-2 text-xs">
          {rec.message && <p className="text-slate-400 italic">{rec.message}</p>}
          {rec.expected_improvement && (
            <div className="flex gap-1">
              <span className="text-slate-500 shrink-0">Expected:</span>
              <span className="text-emerald-400">{rec.expected_improvement}</span>
            </div>
          )}
          {rec.ci_low != null && rec.ci_high != null && (
            <div className="flex gap-1">
              <span className="text-slate-500 shrink-0">95% CI:</span>
              <span className="text-sky-400">[{pct(rec.ci_low)}, {pct(rec.ci_high)}]</span>
            </div>
          )}
          {rec.risk_description && (
            <div className="flex gap-1">
              <span className="text-slate-500 shrink-0">Risk:</span>
              <span className="text-amber-300">{rec.risk_description}</span>
            </div>
          )}
          {rec.rollback_plan && (
            <div className="flex gap-1">
              <span className="text-slate-500 shrink-0">Rollback:</span>
              <span className="text-slate-300">{rec.rollback_plan}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Constants ─────────────────────────────────────────────────────────────────

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

// ── Main ──────────────────────────────────────────────────────────────────────

export function ResearchCommandCenter() {
  const [tab, setTab] = useState<"overview" | "cohorts" | "cube" | "recommendations" | "live">("overview");
  const [cubeDims, setCubeDims] = useState(["score_bucket", "regime"]);

  const health = useQuery({
    queryKey:  ["research", "health"],
    queryFn:   researchService.getHealth,
    staleTime: 5 * 60_000,
  });

  const cohorts = useQuery({
    queryKey:  ["research", "cohorts"],
    queryFn:   () => researchService.getAllCohorts(5),
    staleTime: 5 * 60_000,
    enabled:   tab === "cohorts" || tab === "overview",
  });

  const recs = useQuery({
    queryKey:  ["research", "recommendations"],
    queryFn:   researchService.getRecommendations,
    staleTime: 10 * 60_000,
    enabled:   tab === "recommendations" || tab === "overview",
  });

  const cube = useQuery({
    queryKey:  ["research", "cube", cubeDims],
    queryFn:   () => researchService.queryCube(cubeDims, 5),
    staleTime: 5 * 60_000,
    enabled:   tab === "cube",
  });

  const lvp = useQuery({
    queryKey:  ["research", "live-vs-paper"],
    queryFn:   () => researchService.getLiveVsPaper(90),
    staleTime: 10 * 60_000,
    enabled:   tab === "live",
  });

  const TABS = [
    { id: "overview",        label: "Overview" },
    { id: "cohorts",         label: "Cohort Engine" },
    { id: "cube",            label: "Research Cube" },
    { id: "recommendations", label: "Recommendations" },
    { id: "live",            label: "Live vs Paper" },
  ] as const;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold text-white tracking-tight">Research Command Center</h1>
          <p className="text-xs text-slate-500 mt-0.5">Evidence-driven platform intelligence · Phase 23</p>
        </div>
        <a
          href="/api/v1/research/report/weekly/csv"
          download
          className="text-xs px-3 py-1.5 rounded-md border border-slate-600 text-slate-300 hover:bg-slate-800 hover:text-white transition-colors"
        >
          ↓ Export CSV
        </a>
      </div>

      {/* Tabs */}
      <div className="flex gap-0 border-b border-slate-700/60">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px ${
              tab === t.id
                ? "border-sky-400 text-sky-300"
                : "border-transparent text-slate-500 hover:text-slate-300"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Overview ────────────────────────────────────────────────────────── */}
      {tab === "overview" && (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="lg:col-span-2">
            {health.isLoading ? (
              <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-5 animate-pulse h-52" />
            ) : health.data ? (
              <HealthCard health={health.data} />
            ) : (
              <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-5 text-sm text-slate-500">
                Health data unavailable
              </div>
            )}
          </div>

          {[
            { key: "regime",              label: "Market Regime" },
            { key: "score_bucket",        label: "Score Buckets" },
            { key: "instrument_type",     label: "Instrument" },
            { key: "qualification_grade", label: "Research Grade" },
          ].map(({ key, label }) => (
            <div key={key} className="bg-slate-900 border border-slate-700/60 rounded-xl p-4">
              <CohortTable
                title={label}
                rows={(cohorts.data?.[key] ?? []).slice(0, 6)}
              />
            </div>
          ))}

          <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-4 lg:col-span-2">
            <h3 className="text-[11px] font-bold text-slate-500 uppercase tracking-widest mb-3">
              Top Recommendations
            </h3>
            {recs.data && recs.data.length > 0 ? (
              <div className="space-y-2">
                {recs.data.slice(0, 3).map((r, i) => <RecCard key={i} rec={r} />)}
                {recs.data.length > 3 && (
                  <button onClick={() => setTab("recommendations")} className="text-xs text-sky-400 hover:underline mt-1">
                    View all {recs.data.length} recommendations →
                  </button>
                )}
              </div>
            ) : (
              <p className="text-sm text-slate-600 italic">
                No recommendations yet — accumulate ≥30 completed trades per cohort.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── Cohort Engine ───────────────────────────────────────────────────── */}
      {tab === "cohorts" && (
        <div className="grid gap-4 md:grid-cols-2">
          {COHORT_DIMS.map(({ key, label }) => (
            <div key={key} className="bg-slate-900 border border-slate-700/60 rounded-xl p-4">
              <CohortTable title={label} rows={(cohorts.data?.[key] ?? []).slice(0, 8)} />
            </div>
          ))}
        </div>
      )}

      {/* ── Research Cube ───────────────────────────────────────────────────── */}
      {tab === "cube" && (
        <div className="space-y-4">
          <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-4 space-y-3">
            <div className="text-xs font-semibold text-slate-400">
              Select Dimensions <span className="text-slate-600">(max 3)</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {COHORT_DIMS.map(({ key, label }) => {
                const active = cubeDims.includes(key);
                return (
                  <button
                    key={key}
                    onClick={() =>
                      active
                        ? setCubeDims((p) => p.filter((d) => d !== key))
                        : cubeDims.length < 3 && setCubeDims((p) => [...p, key])
                    }
                    className={`px-3 py-1 text-xs rounded-full border font-medium transition-colors ${
                      active
                        ? "bg-sky-500/20 border-sky-500/50 text-sky-300"
                        : "border-slate-600 text-slate-400 hover:border-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-4">
            {cube.isLoading ? (
              <div className="animate-pulse h-48 bg-slate-800/50 rounded" />
            ) : !cube.data || cube.data.length === 0 ? (
              <p className="text-sm text-slate-600 italic">No cells with ≥5 completed trades for this combination.</p>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="text-xs w-full">
                    <thead>
                      <tr className="border-b border-slate-700/50">
                        {cubeDims.map((d) => (
                          <th key={d} className="text-left py-1.5 pr-3 text-slate-500 font-medium capitalize">
                            {d.replace(/_/g, " ")}
                          </th>
                        ))}
                        <th className="text-right py-1.5 pr-3 text-slate-500 font-medium">n</th>
                        <th className="text-right py-1.5 pr-3 text-slate-500 font-medium">Win%</th>
                        <th className="text-right py-1.5 pr-3 text-slate-500 font-medium">PF</th>
                        <th className="text-right py-1.5 pr-3 text-slate-500 font-medium">Exp</th>
                        <th className="text-right py-1.5 text-slate-500 font-medium">Sharpe</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cube.data.slice(0, 50).map((row, i) => (
                        <tr
                          key={i}
                          className={`border-b border-slate-800/50 last:border-0 ${i % 2 === 0 ? "bg-slate-800/20" : ""}`}
                        >
                          {cubeDims.map((d) => (
                            <td key={d} className="py-1.5 pr-3 text-slate-200 font-medium">
                              {String(row[d] ?? "—")}
                            </td>
                          ))}
                          <td className="text-right py-1.5 pr-3 tabular-nums text-slate-400">{row.trade_count}</td>
                          <td className={`text-right py-1.5 pr-3 tabular-nums ${wrCls(row.win_rate ?? 0)}`}>
                            {pct(row.win_rate)}
                          </td>
                          <td className={`text-right py-1.5 pr-3 tabular-nums ${pfCls(row.profit_factor)}`}>
                            {num(row.profit_factor)}×
                          </td>
                          <td className={`text-right py-1.5 pr-3 tabular-nums ${expCls(row.expectancy)}`}>
                            {num(row.expectancy, 4)}
                          </td>
                          <td className="text-right py-1.5 tabular-nums text-slate-300">{num(row.sharpe)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {cube.data.length > 50 && (
                  <p className="text-xs text-slate-600 mt-2">Showing top 50 of {cube.data.length} cells</p>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Recommendations ─────────────────────────────────────────────────── */}
      {tab === "recommendations" && (
        <div className="space-y-2">
          {recs.isLoading ? (
            <div className="animate-pulse space-y-2">
              {[1, 2, 3].map((i) => <div key={i} className="h-14 bg-slate-800/50 rounded-lg" />)}
            </div>
          ) : !recs.data || recs.data.length === 0 ? (
            <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-8 text-center space-y-1">
              <p className="text-sm text-slate-400">No recommendations available yet.</p>
              <p className="text-xs text-slate-600">Need ≥30 completed trades per cohort for statistical significance.</p>
            </div>
          ) : (
            <>
              <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-4 flex items-center gap-6 text-sm">
                <div>
                  <span className="font-bold text-white">{recs.data.length}</span>
                  <span className="text-slate-500 ml-1.5">total</span>
                </div>
                <div>
                  <span className="font-bold text-sky-400">
                    {recs.data.filter((r) => r.status === "READY_FOR_REVIEW").length}
                  </span>
                  <span className="text-slate-500 ml-1.5">ready for review</span>
                </div>
                <div>
                  <span className="font-bold text-amber-400">
                    {recs.data.filter((r) => r.status === "EMERGING").length}
                  </span>
                  <span className="text-slate-500 ml-1.5">emerging</span>
                </div>
              </div>
              {recs.data.map((rec, i) => <RecCard key={i} rec={rec} />)}
            </>
          )}
        </div>
      )}

      {/* ── Live vs Paper ───────────────────────────────────────────────────── */}
      {tab === "live" && (
        <div className="space-y-4">
          {lvp.isLoading ? (
            <div className="animate-pulse h-64 bg-slate-800/50 rounded-xl" />
          ) : !lvp.data ? (
            <p className="text-sm text-slate-500">Could not load comparison data.</p>
          ) : (
            <>
              {!lvp.data.has_live_data && (
                <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-sm text-amber-300">
                  No live trading data yet. Gate 2 requires ≥50 completed trades and readiness ≥65.
                </div>
              )}

              <div className="grid md:grid-cols-2 gap-4">
                {(["paper", "live"] as const).map((mode) => {
                  const s = lvp.data![mode];
                  return (
                    <div key={mode} className="bg-slate-900 border border-slate-700/60 rounded-xl p-4 space-y-3">
                      <h3 className="font-bold text-sm text-white capitalize tracking-wide">
                        {mode === "paper" ? "📄 Paper" : "🔴 Live"} Trading
                      </h3>
                      <div className="grid grid-cols-2 gap-y-2 text-sm">
                        {[
                          ["Completed", s.n, "text-slate-200"],
                          ["Win Rate", pct(s.win_rate), wrCls(s.win_rate)],
                          ["Profit Factor", `${num(s.profit_factor)}×`, pfCls(s.profit_factor)],
                          ["Expectancy", num(s.expectancy, 4), expCls(s.expectancy)],
                          ["A/B Grade %", pct(s.ab_grade_pct), s.ab_grade_pct >= 60 ? "text-emerald-400" : "text-amber-400"],
                          ["Data Quality", num(s.avg_data_quality, 0), "text-slate-300"],
                        ].map(([label, value, cls]) => (
                          <div key={String(label)} className="contents">
                            <div className="text-slate-500 text-xs">{label}</div>
                            <div className={`text-right font-semibold tabular-nums text-xs ${cls}`}>{value}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>

              {lvp.data.has_live_data && (
                <div className="bg-slate-900 border border-slate-700/60 rounded-xl p-4">
                  <h3 className="font-bold text-sm text-white mb-3">Drift Analysis</h3>
                  <table className="text-xs w-full">
                    <thead>
                      <tr className="border-b border-slate-700/50">
                        {["Metric", "Paper", "Live", "Delta", "Direction", "Sig"].map((h, i) => (
                          <th key={h} className={`py-1.5 text-slate-500 font-medium ${i === 0 ? "text-left" : "text-right"} ${i > 0 ? "pr-3" : "pr-3"}`}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {lvp.data.drift_checks.map((d) => (
                        <tr key={d.metric} className="border-b border-slate-800/50 last:border-0">
                          <td className="py-1.5 pr-3 text-slate-300 font-medium capitalize">{d.metric.replace(/_/g, " ")}</td>
                          <td className="text-right py-1.5 pr-3 tabular-nums text-slate-400">{num(d.paper, 3)}</td>
                          <td className="text-right py-1.5 pr-3 tabular-nums text-slate-300">{num(d.live, 3)}</td>
                          <td className={`text-right py-1.5 pr-3 tabular-nums font-semibold ${(d.delta ?? 0) > 0 ? "text-emerald-400" : (d.delta ?? 0) < 0 ? "text-rose-400" : "text-slate-500"}`}>
                            {d.delta != null ? (d.delta > 0 ? "+" : "") + num(d.delta, 3) : "—"}
                          </td>
                          <td className={`text-right py-1.5 pr-3 text-xs font-semibold ${d.direction === "IMPROVED" ? "text-emerald-400" : d.direction === "DEGRADED" ? "text-rose-400" : "text-slate-500"}`}>
                            {d.direction}
                          </td>
                          <td className={`text-right py-1.5 text-sm ${d.significant ? "text-amber-400" : "text-slate-700"}`}>
                            {d.significant ? "★" : "·"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-[11px] text-slate-600 mt-2">★ p &lt; 0.05 (statistically significant)</p>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
