"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  tradeManagementService,
  type TmiSummary,
  type TmiSignal,
  type CaptureRatioDistribution,
  type RegimeAnalysis,
  type WeeklyReport,
} from "@/services/trade-management.service";

// ─── Constants ────────────────────────────────────────────────────────────────

const CLASSIFICATION_COLORS: Record<string, string> = {
  BAD_ENTRY:                    "bg-red-500/15 text-red-400 border-red-500/30",
  GOOD_ENTRY_POOR_EXIT:         "bg-amber-500/15 text-amber-400 border-amber-500/30",
  GOOD_ENTRY_UNREALISTIC_TARGET: "bg-orange-500/15 text-orange-400 border-orange-500/30",
  GOOD_ENTRY_PREMIUM_DECAY:     "bg-purple-500/15 text-purple-400 border-purple-500/30",
  GOOD_ENTRY_REGIME_REVERSAL:   "bg-blue-500/15 text-blue-400 border-blue-500/30",
  GOOD_ENTRY_CAPTURED:          "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

const CLASSIFICATION_LABELS: Record<string, string> = {
  BAD_ENTRY:                    "Bad Entry",
  GOOD_ENTRY_POOR_EXIT:         "Poor Exit",
  GOOD_ENTRY_UNREALISTIC_TARGET: "Target Too High",
  GOOD_ENTRY_PREMIUM_DECAY:     "Premium Decay",
  GOOD_ENTRY_REGIME_REVERSAL:   "Regime Reversal",
  GOOD_ENTRY_CAPTURED:          "Captured",
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <p className="text-2xl font-bold text-slate-100">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function ClassificationBadge({ cls }: { cls: string }) {
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[10px] font-semibold ${CLASSIFICATION_COLORS[cls] ?? "text-slate-400 border-slate-600"}`}>
      {CLASSIFICATION_LABELS[cls] ?? cls}
    </span>
  );
}

function SummaryCards({ data, days }: { data: TmiSummary; days: number }) {
  const capRatioPct = (data.avg_capture_ratio * 100).toFixed(0);
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
      <StatCard
        label="Total Signals"
        value={String(data.total_accepted)}
        sub={`${days}d window`}
      />
      <StatCard
        label="Avg Capture Ratio"
        value={`${capRatioPct}%`}
        sub="of MFE actually kept"
      />
      <StatCard
        label="Avg MFE"
        value={`${data.avg_mfe_pct.toFixed(1)}%`}
        sub="peak available profit"
      />
      <StatCard
        label="Avg Profit Surrendered"
        value={`${data.avg_profit_surrendered_pct.toFixed(1)}%`}
        sub="gains given back"
      />
    </div>
  );
}

function ProfitTierBar({ data }: { data: TmiSummary }) {
  const total = data.signals_with_mfe || 1;
  const tiers = [
    { label: "+10%", count: data.profit_tiers.mfe_gte_10pct, color: "bg-emerald-400" },
    { label: "+20%", count: data.profit_tiers.mfe_gte_20pct, color: "bg-emerald-500" },
    { label: "+30%", count: data.profit_tiers.mfe_gte_30pct, color: "bg-emerald-600" },
    { label: "+40%", count: data.profit_tiers.mfe_gte_40pct, color: "bg-blue-500" },
    { label: "+50%", count: data.profit_tiers.mfe_gte_50pct, color: "bg-blue-600" },
  ];

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5 mb-4">
      <h3 className="text-sm font-semibold text-slate-200 mb-4">MFE Profit Tiers</h3>
      <div className="space-y-3">
        {tiers.map((t) => (
          <div key={t.label} className="flex items-center gap-3">
            <span className="text-xs text-slate-400 w-10 shrink-0">{t.label}</span>
            <div className="flex-1 h-4 rounded bg-slate-700/50 relative overflow-hidden">
              <div
                className={`absolute inset-y-0 left-0 rounded ${t.color}`}
                style={{ width: `${Math.min(100, (t.count / total) * 100)}%` }}
              />
            </div>
            <span className="text-xs text-slate-300 w-16 text-right">
              {t.count} / {total}
            </span>
            <span className="text-xs text-slate-500 w-10 text-right">
              {total > 0 ? ((t.count / total) * 100).toFixed(0) : 0}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ClassificationBreakdown({ data }: { data: TmiSummary }) {
  const cls = data.classifications;
  const total = Object.values(cls).reduce((a, b) => a + b, 0) || 1;
  const entries = Object.entries(cls) as [keyof typeof cls, number][];

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5 mb-4">
      <h3 className="text-sm font-semibold text-slate-200 mb-4">Trade Classifications</h3>
      <div className="space-y-2.5">
        {entries.map(([key, count]) => (
          <div key={key} className="flex items-center gap-3">
            <ClassificationBadge cls={key} />
            <div className="flex-1 h-3 rounded bg-slate-700/50 relative overflow-hidden">
              <div
                className={`absolute inset-y-0 left-0 rounded ${CLASSIFICATION_COLORS[key]?.split(" ")[0]}`}
                style={{ width: `${(count / total) * 100}%`, opacity: 0.7 }}
              />
            </div>
            <span className="text-xs text-slate-300 w-6 text-right">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CaptureRatioPanel({ data }: { data: CaptureRatioDistribution }) {
  const buckets = [
    { label: "< 0%",     count: data.below_zero,    color: "bg-red-500" },
    { label: "0–25%",    count: data.zero_to_25pct,  color: "bg-orange-500" },
    { label: "25–50%",   count: data["25_to_50pct"], color: "bg-amber-500" },
    { label: "50–75%",   count: data["50_to_75pct"], color: "bg-emerald-400" },
    { label: "75–100%",  count: data["75_to_100pct"],color: "bg-emerald-500" },
    { label: "≥ 100%",   count: data.full_or_above,  color: "bg-blue-500" },
  ];
  const total = buckets.reduce((s, b) => s + b.count, 0) || 1;

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5 mb-4">
      <h3 className="text-sm font-semibold text-slate-200 mb-1">Capture Ratio Distribution</h3>
      <p className="text-xs text-slate-500 mb-4">How much of peak profit (MFE) was actually kept</p>
      <div className="space-y-2.5">
        {buckets.map((b) => (
          <div key={b.label} className="flex items-center gap-3">
            <span className="text-xs text-slate-400 w-16 shrink-0">{b.label}</span>
            <div className="flex-1 h-3 rounded bg-slate-700/50 relative overflow-hidden">
              <div
                className={`absolute inset-y-0 left-0 rounded ${b.color}`}
                style={{ width: `${(b.count / total) * 100}%`, opacity: 0.8 }}
              />
            </div>
            <span className="text-xs text-slate-300 w-6 text-right">{b.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RegimeTable({ regimes }: { regimes: RegimeAnalysis[] }) {
  if (!regimes.length) {
    return (
      <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5 mb-4 text-slate-500 text-sm">
        No regime data yet — need settled signals with MFE data.
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5 mb-4">
      <h3 className="text-sm font-semibold text-slate-200 mb-3">Regime Reversal Analysis</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500 border-b border-slate-700/60">
              <th className="text-left pb-2 font-medium">Regime</th>
              <th className="text-right pb-2 font-medium">Total</th>
              <th className="text-right pb-2 font-medium">Avg MFE</th>
              <th className="text-right pb-2 font-medium">Avg Surrender</th>
              <th className="text-right pb-2 font-medium">Avg Capture</th>
              <th className="text-right pb-2 font-medium">Reversals</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/40">
            {regimes.map((r) => (
              <tr key={r.regime} className="text-slate-300">
                <td className="py-2 font-medium text-slate-200">{r.regime}</td>
                <td className="py-2 text-right">{r.total}</td>
                <td className="py-2 text-right">{r.avg_mfe != null ? `${Number(r.avg_mfe).toFixed(1)}%` : "—"}</td>
                <td className={`py-2 text-right ${Number(r.avg_surrender) > 10 ? "text-amber-400" : ""}`}>
                  {r.avg_surrender != null ? `${Number(r.avg_surrender).toFixed(1)}%` : "—"}
                </td>
                <td className="py-2 text-right">
                  {r.avg_capture != null ? `${(Number(r.avg_capture) * 100).toFixed(0)}%` : "—"}
                </td>
                <td className={`py-2 text-right ${r.reversals > 0 ? "text-red-400" : "text-slate-500"}`}>
                  {r.reversals}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SignalTable({ signals }: { signals: TmiSignal[] }) {
  if (!signals.length) {
    return (
      <div className="text-slate-500 text-sm p-4">No signals with MFE data yet.</div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-500 border-b border-slate-700/60">
            <th className="text-left pb-2 font-medium">Ticker</th>
            <th className="text-left pb-2 font-medium">Dir</th>
            <th className="text-right pb-2 font-medium">MFE</th>
            <th className="text-right pb-2 font-medium">Return</th>
            <th className="text-right pb-2 font-medium">Capture</th>
            <th className="text-right pb-2 font-medium">Surrender</th>
            <th className="text-left pb-2 font-medium">Classification</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-700/40">
          {signals.map((s, i) => (
            <tr key={i} className="text-slate-300">
              <td className="py-2 font-medium text-slate-100">{s.ticker}</td>
              <td className="py-2">{s.direction}</td>
              <td className="py-2 text-right text-emerald-400">
                {s.mfe_pct != null ? `${Number(s.mfe_pct).toFixed(1)}%` : "—"}
              </td>
              <td className={`py-2 text-right ${(s.current_return_pct ?? 0) >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {s.current_return_pct != null ? `${Number(s.current_return_pct).toFixed(1)}%` : "—"}
              </td>
              <td className="py-2 text-right">
                {s.capture_ratio != null ? `${(Number(s.capture_ratio) * 100).toFixed(0)}%` : "—"}
              </td>
              <td className={`py-2 text-right ${Number(s.profit_surrender_pct) > 10 ? "text-amber-400" : ""}`}>
                {s.profit_surrender_pct != null ? `${Number(s.profit_surrender_pct).toFixed(1)}%` : "—"}
              </td>
              <td className="py-2">
                {s.trade_classification ? <ClassificationBadge cls={s.trade_classification} /> : <span className="text-slate-600">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InterpretationPanel({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-5 mb-4">
      <h3 className="text-sm font-semibold text-blue-300 mb-3">System Interpretation</h3>
      <ul className="space-y-2">
        {lines.map((line, i) => (
          <li key={i} className="flex gap-2 text-xs text-slate-300">
            <span className="text-blue-400 mt-0.5 shrink-0">›</span>
            {line}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─── Main View ────────────────────────────────────────────────────────────────

export default function TradeManagementView() {
  const [days, setDays] = useState(30);
  const [tab, setTab] = useState<"overview" | "signals" | "regimes" | "weekly">("overview");

  const summaryQ = useQuery({
    queryKey: ["tmi-summary", days],
    queryFn: () => tradeManagementService.getSummary(days),
    refetchInterval: 120_000,
  });

  const captureQ = useQuery({
    queryKey: ["tmi-capture", days],
    queryFn: () => tradeManagementService.getCaptureRatio(days),
    enabled: tab === "overview",
    refetchInterval: 120_000,
  });

  const signalsQ = useQuery({
    queryKey: ["tmi-signals", days],
    queryFn: () => tradeManagementService.getProfitTiers(days),
    enabled: tab === "signals",
  });

  const regimesQ = useQuery({
    queryKey: ["tmi-regimes", days],
    queryFn: () => tradeManagementService.getRegimeAnalysis(days),
    enabled: tab === "regimes",
  });

  const weeklyQ = useQuery({
    queryKey: ["tmi-weekly"],
    queryFn: () => tradeManagementService.getWeeklyReport(7),
    enabled: tab === "weekly",
  });

  const classifyMut = useMutation({
    mutationFn: () => tradeManagementService.runClassification(),
  });

  const summary = summaryQ.data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-100">Trade Management Intelligence</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Capture ratio · Profit surrender · Trade classification · Regime analysis
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-lg border border-slate-700/60 bg-slate-800 text-xs text-slate-300 px-3 py-1.5"
          >
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={60}>Last 60 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button
            onClick={() => classifyMut.mutate()}
            disabled={classifyMut.isPending}
            className="rounded-lg border border-slate-700/60 bg-slate-800 text-xs text-slate-300 px-3 py-1.5 hover:bg-slate-700 disabled:opacity-50"
          >
            {classifyMut.isPending ? "Classifying…" : "Run Classification"}
          </button>
        </div>
      </div>

      {/* Classify result */}
      {classifyMut.data && (
        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-4 py-2 text-xs text-emerald-300">
          Classified {classifyMut.data.updated} signals · {classifyMut.data.errors} errors
        </div>
      )}

      {/* Summary cards */}
      {summary && <SummaryCards data={summary} days={days} />}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-700/60">
        {(["overview", "signals", "regimes", "weekly"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-xs font-medium capitalize transition-colors ${
              tab === t
                ? "text-slate-100 border-b-2 border-blue-500"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            {t === "weekly" ? "Weekly Report" : t}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "overview" && summary && (
        <div className="grid md:grid-cols-2 gap-4">
          <ProfitTierBar data={summary} />
          <ClassificationBreakdown data={summary} />
          {captureQ.data && <CaptureRatioPanel data={captureQ.data} />}
        </div>
      )}

      {tab === "signals" && (
        <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
          <h3 className="text-sm font-semibold text-slate-200 mb-3">
            Signal MFE Breakdown ({days}d)
          </h3>
          {signalsQ.isLoading ? (
            <p className="text-slate-500 text-sm">Loading…</p>
          ) : (
            <SignalTable signals={signalsQ.data?.signals ?? []} />
          )}
        </div>
      )}

      {tab === "regimes" && (
        <>
          {regimesQ.isLoading ? (
            <p className="text-slate-500 text-sm">Loading…</p>
          ) : (
            <RegimeTable regimes={regimesQ.data?.regimes ?? []} />
          )}
        </>
      )}

      {tab === "weekly" && (
        <>
          {weeklyQ.isLoading ? (
            <p className="text-slate-500 text-sm">Generating report…</p>
          ) : weeklyQ.data ? (
            <div className="space-y-4">
              <InterpretationPanel lines={weeklyQ.data.interpretation} />
              <SummaryCards data={weeklyQ.data} days={7} />
              {weeklyQ.data.capture_ratio_distribution && (
                <CaptureRatioPanel data={weeklyQ.data.capture_ratio_distribution} />
              )}
              <RegimeTable regimes={weeklyQ.data.regime_analysis} />
              <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
                <h3 className="text-sm font-semibold text-slate-200 mb-3">Top Signals This Week</h3>
                <SignalTable signals={weeklyQ.data.top_signals} />
              </div>
            </div>
          ) : null}
        </>
      )}

      {/* Empty state */}
      {summary && summary.signals_with_mfe === 0 && (
        <div className="rounded-xl border border-slate-700/40 bg-slate-800/20 p-8 text-center">
          <p className="text-slate-400 text-sm font-medium">No MFE data yet</p>
          <p className="text-slate-600 text-xs mt-1">
            TMI metrics appear as signals settle. Check back after market close.
          </p>
        </div>
      )}
    </div>
  );
}
