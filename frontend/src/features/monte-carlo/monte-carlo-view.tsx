"use client";

import { useEffect, useState } from "react";
import { monteCarloService, strategyVersioningService } from "@/services/research.service";

export function MonteCarloView() {
  const [versions, setVersions] = useState<{ id: string; name: string }[]>([]);
  const [versionId, setVersionId] = useState("");
  const [nSims, setNSims] = useState("1000");
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [summary, setSummary] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    strategyVersioningService.list().then((d) => setVersions(d.versions ?? []));
  }, []);

  const start = async () => {
    if (!versionId) return;
    setRunning(true);
    setSummary(null);
    try {
      const res = await monteCarloService.start({
        version_id: versionId,
        n_sims: parseInt(nSims, 10),
        lookback_days: 252,
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
    monteCarloService.results(runId).then((d) => setSummary(d.summary ?? null));
  };

  const fmt = (v?: number) => (v == null ? "—" : v.toFixed(3));

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Monte Carlo Simulation</h1>

      <div className="rounded-lg border p-4 space-y-3">
        <div className="font-medium text-sm">Configure Simulation</div>
        <div className="flex gap-2 items-center">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={versionId}
            onChange={(e) => setVersionId(e.target.value)}
          >
            <option value="">Select version…</option>
            {versions.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
          <input
            className="border rounded px-2 py-1 text-sm w-24"
            type="number"
            min={10}
            max={10000}
            value={nSims}
            onChange={(e) => setNSims(e.target.value)}
            placeholder="Simulations"
          />
          <button
            className="bg-primary text-primary-foreground px-3 py-1 rounded text-sm disabled:opacity-50"
            onClick={start}
            disabled={running || !versionId}
          >
            {running ? "Running…" : "Start"}
          </button>
          {runId && (
            <button className="border px-3 py-1 rounded text-sm" onClick={loadResults}>
              Load Results
            </button>
          )}
        </div>
      </div>

      {summary && (
        <div className="rounded-lg border p-4">
          <div className="font-medium mb-3">Distribution Summary</div>
          <div className="grid grid-cols-5 gap-4">
            {["p5", "p25", "p50", "p75", "p95"].map((k) => (
              <div key={k} className="text-center">
                <div className="text-xs text-muted-foreground uppercase">{k}</div>
                <div className="text-lg font-semibold tabular-nums">{fmt(summary[k])}</div>
              </div>
            ))}
          </div>
          {summary.prob_positive != null && (
            <div className="mt-4 text-sm text-muted-foreground">
              Probability of positive outcome:{" "}
              <span className="font-medium text-foreground">
                {(summary.prob_positive * 100).toFixed(1)}%
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
