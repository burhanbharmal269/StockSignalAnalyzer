"use client";

import { useOperatorStatus } from "@/hooks/use-analytics-intelligence";
import type { RegimeMixEntry } from "@/services/analytics-intelligence.service";

const STATUS_COLORS: Record<string, string> = {
  HEALTHY: "text-emerald-400",
  NORMAL:  "text-emerald-400",
  WARNING: "text-amber-400",
  CRITICAL: "text-red-400",
  MARKET_CLOSED: "text-slate-500",
};

function StatCard({ label, value, sub, highlight }: {
  label: string; value: string | number; sub?: string; highlight?: "warn" | "crit" | "ok";
}) {
  const valueClass =
    highlight === "crit" ? "text-red-400" :
    highlight === "warn" ? "text-amber-400" :
    highlight === "ok"   ? "text-emerald-400" :
    "text-slate-100";
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-4">
      <p className="text-xs text-slate-400 uppercase tracking-wider">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${valueClass}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function RegimeBar({ entry, total }: { entry: RegimeMixEntry; total: number }) {
  const pct = total > 0 ? entry.pct : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs font-mono text-slate-400 w-32 shrink-0">{entry.regime}</span>
      <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
      <span className="text-xs text-slate-400 tabular-nums w-12 text-right">{pct.toFixed(1)}%</span>
      <span className="text-xs text-slate-500 tabular-nums w-8 text-right">{entry.count}</span>
    </div>
  );
}

export default function OperatorView() {
  const status = useOperatorStatus();
  const d = status.data;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Operator Status</h1>
          <p className="text-sm text-slate-400 mt-0.5">
            Live scanner status panel — auto-refreshes every 30s
          </p>
        </div>
        {d && (
          <div className="text-right">
            <p className="text-xs text-slate-500">{d.ist_time}</p>
            <p className="text-xs text-slate-500">v{d.scanner_version}</p>
          </div>
        )}
      </div>

      {status.isLoading && (
        <p className="text-sm text-slate-500">Loading operator panel…</p>
      )}

      {d?.error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          {d.error}
        </div>
      )}

      {d && !d.error && (
        <>
          {/* Scanner state */}
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Scanner State
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              <StatCard
                label="Last Scan"
                value={d.last_scan_time
                  ? new Date(d.last_scan_time).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit" })
                  : "—"}
                sub="IST"
              />
              <StatCard
                label="Next Scan ETA"
                value={d.next_scan_eta}
                highlight={d.next_scan_eta === "MARKET_CLOSED" ? "warn" : undefined}
              />
              <StatCard
                label="Active Signals"
                value={d.active_signals}
                sub="open accepted"
              />
              <StatCard
                label="Portfolio Heat"
                value={d.portfolio_heat}
                sub="open positions"
              />
            </div>
          </div>

          {/* Today's activity */}
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
            <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Today (IST Day)
            </h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <StatCard label="Symbols Scanned" value={d.symbols_processed_today} />
              <StatCard label="Candidates" value={d.candidates_today} sub="all signals" />
              <StatCard label="Accepted" value={d.signals_generated_today} sub="reached order stage" />
              <StatCard
                label="Targets Hit"
                value={d.targets_hit_today}
                highlight={d.targets_hit_today > 0 ? "ok" : undefined}
              />
              <StatCard
                label="Stops Hit"
                value={d.stops_hit_today}
                highlight={d.stops_hit_today > 0 ? "warn" : undefined}
              />
            </div>
          </div>

          {/* Quality */}
          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
              <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Quality Scores (last 2h)
              </h2>
              <div className="grid grid-cols-2 gap-3">
                <StatCard
                  label="Data Quality"
                  value={d.data_quality_score != null ? `${d.data_quality_score}` : "—"}
                  sub="avg DQ score"
                  highlight={
                    d.data_quality_score == null ? undefined :
                    d.data_quality_score >= 80 ? "ok" :
                    d.data_quality_score >= 60 ? "warn" : "crit"
                  }
                />
                <StatCard
                  label="Exec Quality"
                  value={d.execution_quality_score != null ? `${d.execution_quality_score}` : "—"}
                  sub="slippage-based"
                  highlight={
                    d.execution_quality_score == null ? undefined :
                    d.execution_quality_score >= 80 ? "ok" :
                    d.execution_quality_score >= 60 ? "warn" : "crit"
                  }
                />
              </div>
            </div>

            {/* Regime mix */}
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-5">
              <h2 className="mb-4 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Regime Mix (last 3h)
              </h2>
              {d.current_regime_mix.length === 0 ? (
                <p className="text-sm text-slate-500">No signals in last 3 hours</p>
              ) : (
                <div className="space-y-2">
                  {d.current_regime_mix.map((r) => (
                    <RegimeBar
                      key={r.regime}
                      entry={r}
                      total={d.current_regime_mix.reduce((s, x) => s + x.count, 0)}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
