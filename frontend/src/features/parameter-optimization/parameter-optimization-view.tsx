"use client";

import { useEffect, useState } from "react";
import { optimizationService, strategyVersioningService } from "@/services/research.service";

interface OptResult {
  params: Record<string, number>;
  sharpe?: number;
  sortino?: number;
  win_rate?: number;
  profit_factor?: number;
  trade_count?: number;
}

export function ParameterOptimizationView() {
  const [versions, setVersions] = useState<{ id: string; name: string }[]>([]);
  const [versionId, setVersionId] = useState("");
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [results, setResults] = useState<OptResult[]>([]);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    strategyVersioningService.list().then((d) => setVersions(d.versions ?? []));
  }, []);

  const start = async () => {
    if (!versionId) return;
    setRunning(true);
    setResults([]);
    setStatus("RUNNING");
    try {
      const res = await optimizationService.start({
        version_id: versionId,
        param_grid: {
          oi_buildup: [20, 25, 30],
          trend: [15, 20, 25],
          min_score: [65, 70, 75],
        },
        metric: "sharpe",
        lookback_days: 252,
      });
      setRunId(res.run_id);
    } catch (e) {
      console.error(e);
      setStatus("ERROR");
    } finally {
      setRunning(false);
    }
  };

  const loadResults = () => {
    if (!runId) return;
    optimizationService.results(runId).then((d) => {
      setResults(d.results ?? []);
      setStatus(d.status ?? "DONE");
    });
  };

  const fmt = (v?: number) => (v == null ? "—" : v.toFixed(3));

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Parameter Optimization</h1>

      <div className="rounded-lg border p-4 space-y-3">
        <div className="font-medium text-sm">Start Grid Search</div>
        <div className="flex gap-2 items-center">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={versionId}
            onChange={(e) => setVersionId(e.target.value)}
          >
            <option value="">Select version…</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
          <button
            className="bg-primary text-primary-foreground px-3 py-1 rounded text-sm disabled:opacity-50"
            onClick={start}
            disabled={running || !versionId}
          >
            {running ? "Starting…" : "Run Grid Search"}
          </button>
          {runId && (
            <button className="border px-3 py-1 rounded text-sm" onClick={loadResults}>
              Refresh Results
            </button>
          )}
          {status && <span className="text-xs text-muted-foreground">Status: {status}</span>}
        </div>
        {runId && <div className="text-xs text-muted-foreground">Run ID: {runId}</div>}
      </div>

      {results.length > 0 && (
        <div className="rounded-lg border">
          <div className="px-4 py-3 border-b font-medium">Results ({results.length} combos)</div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left bg-muted/40">
                <th className="px-4 py-2">Sharpe</th>
                <th className="px-4 py-2">Sortino</th>
                <th className="px-4 py-2">Win Rate</th>
                <th className="px-4 py-2">Profit Factor</th>
                <th className="px-4 py-2">Trades</th>
                <th className="px-4 py-2">Params</th>
              </tr>
            </thead>
            <tbody>
              {results.slice(0, 50).map((r, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/20">
                  <td className="px-4 py-2 tabular-nums">{fmt(r.sharpe)}</td>
                  <td className="px-4 py-2 tabular-nums">{fmt(r.sortino)}</td>
                  <td className="px-4 py-2 tabular-nums">{r.win_rate != null ? `${(r.win_rate * 100).toFixed(1)}%` : "—"}</td>
                  <td className="px-4 py-2 tabular-nums">{fmt(r.profit_factor)}</td>
                  <td className="px-4 py-2 tabular-nums">{r.trade_count ?? "—"}</td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">{JSON.stringify(r.params)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
