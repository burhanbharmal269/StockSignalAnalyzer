"use client";

import { useEffect, useState } from "react";
import { falsePositiveService } from "@/services/research.service";

interface FPRow {
  component: string;
  score_bucket: string;
  false_positive_rate?: number;
  false_negative_rate?: number;
  sample_size?: number;
}

const COMPONENTS = ["oi_buildup", "trend", "option_chain", "volume", "vwap", "sentiment", "iv_analysis"];

export function FalsePositiveView() {
  const [data, setData] = useState<FPRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [computing, setComputing] = useState(false);
  const [selectedComponent, setSelectedComponent] = useState<string>("all");

  const load = () => {
    setLoading(true);
    falsePositiveService
      .get(90)
      .then((d) => setData(d.analysis ?? []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const compute = async () => {
    setComputing(true);
    try {
      await falsePositiveService.compute(90);
      load();
    } catch (e) {
      console.error(e);
    } finally {
      setComputing(false);
    }
  };

  const filtered = selectedComponent === "all"
    ? data
    : data.filter((r) => r.component === selectedComponent);

  const rateCell = (rate?: number) => {
    if (rate == null) return "—";
    const pct = (rate * 100).toFixed(1) + "%";
    const cls = rate > 0.4 ? "text-red-600 font-semibold" : rate > 0.25 ? "text-yellow-600" : "text-green-600";
    return <span className={cls}>{pct}</span>;
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">False Positive Analysis</h1>
        <div className="flex gap-2 items-center">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={selectedComponent}
            onChange={(e) => setSelectedComponent(e.target.value)}
          >
            <option value="all">All components</option>
            {COMPONENTS.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <button
            className="bg-primary text-primary-foreground px-3 py-1 rounded text-sm disabled:opacity-50"
            onClick={compute}
            disabled={computing}
          >
            {computing ? "Computing…" : "Recompute"}
          </button>
        </div>
      </div>

      <div className="rounded-lg border">
        {loading ? (
          <div className="p-4 text-sm text-muted-foreground">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left bg-muted/40">
                <th className="px-4 py-2">Component</th>
                <th className="px-4 py-2">Score Bucket</th>
                <th className="px-4 py-2 text-right">FP Rate</th>
                <th className="px-4 py-2 text-right">FN Rate</th>
                <th className="px-4 py-2 text-right">Samples</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/20">
                  <td className="px-4 py-2 font-medium">{row.component}</td>
                  <td className="px-4 py-2">{row.score_bucket}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{rateCell(row.false_positive_rate)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{rateCell(row.false_negative_rate)}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{row.sample_size ?? "—"}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-4 text-center text-muted-foreground">
                    No data — click Recompute
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
