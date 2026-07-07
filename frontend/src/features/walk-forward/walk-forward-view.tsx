"use client";

import { useEffect, useState } from "react";
import { walkForwardService, strategyVersioningService } from "@/services/research.service";

interface Window {
  window_idx: number;
  train_from: string;
  train_to: string;
  oos_sharpe?: number;
  oos_win_rate?: number;
  oos_trade_count?: number;
}

export function WalkForwardView() {
  const [versions, setVersions] = useState<{ id: string; name: string }[]>([]);
  const [versionId, setVersionId] = useState("");
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [windows, setWindows] = useState<Window[]>([]);
  const [aggregate, setAggregate] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    strategyVersioningService.list().then((d) => setVersions(d.versions ?? []));
  }, []);

  const start = async () => {
    if (!versionId) return;
    setRunning(true);
    setWindows([]);
    setAggregate(null);
    try {
      const now = new Date();
      const fromDt = new Date(now);
      fromDt.setFullYear(fromDt.getFullYear() - 1);
      const res = await walkForwardService.start({
        version_id: versionId,
        from_dt: fromDt.toISOString(),
        to_dt: now.toISOString(),
        n_windows: 5,
      });
      setRunId(res.run_id);
    } catch (e) {
      console.error(e);
    } finally {
      setRunning(false);
    }
  };

  const loadResults = () => {
    if (!runId) return;
    Promise.all([
      walkForwardService.windows(runId),
      walkForwardService.aggregate(runId),
    ]).then(([w, a]) => {
      setWindows(w.windows ?? []);
      setAggregate(a);
    });
  };

  const fmt = (v?: number) => (v == null ? "—" : v.toFixed(3));

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Walk-Forward Analysis</h1>

      <div className="rounded-lg border p-4 space-y-3">
        <div className="font-medium text-sm">Run Walk-Forward (1 year, 5 windows)</div>
        <div className="flex gap-2 items-center">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={versionId}
            onChange={(e) => setVersionId(e.target.value)}
          >
            <option value="">Select version…</option>
            {versions.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          <button
            className="bg-primary text-primary-foreground px-3 py-1 rounded text-sm disabled:opacity-50"
            onClick={start}
            disabled={running || !versionId}
          >
            {running ? "Starting…" : "Start"}
          </button>
          {runId && (
            <button className="border px-3 py-1 rounded text-sm" onClick={loadResults}>
              Load Results
            </button>
          )}
        </div>
      </div>

      {aggregate && (
        <div className="rounded-lg border p-4 grid grid-cols-4 gap-4">
          {Object.entries(aggregate).map(([k, v]) => (
            <div key={k}>
              <div className="text-xs text-muted-foreground">{k}</div>
              <div className="font-semibold">{typeof v === "number" ? v.toFixed(4) : String(v)}</div>
            </div>
          ))}
        </div>
      )}

      {windows.length > 0 && (
        <div className="rounded-lg border">
          <div className="px-4 py-3 border-b font-medium">OOS Windows</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left bg-muted/40">
                <th className="px-4 py-2">#</th>
                <th className="px-4 py-2">Train From</th>
                <th className="px-4 py-2">Train To</th>
                <th className="px-4 py-2">OOS Sharpe</th>
                <th className="px-4 py-2">OOS Win Rate</th>
                <th className="px-4 py-2">OOS Trades</th>
              </tr>
            </thead>
            <tbody>
              {windows.map((w) => (
                <tr key={w.window_idx} className="border-b last:border-0 hover:bg-muted/20">
                  <td className="px-4 py-2">{w.window_idx + 1}</td>
                  <td className="px-4 py-2">{w.train_from ? new Date(w.train_from).toLocaleDateString() : "—"}</td>
                  <td className="px-4 py-2">{w.train_to ? new Date(w.train_to).toLocaleDateString() : "—"}</td>
                  <td className="px-4 py-2 tabular-nums">{fmt(w.oos_sharpe)}</td>
                  <td className="px-4 py-2 tabular-nums">{w.oos_win_rate != null ? `${(w.oos_win_rate * 100).toFixed(1)}%` : "—"}</td>
                  <td className="px-4 py-2 tabular-nums">{w.oos_trade_count ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
