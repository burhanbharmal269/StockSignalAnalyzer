"use client";

import { useEffect, useState } from "react";
import { regimePerformanceService } from "@/services/research.service";

interface RegimeRow {
  regime: string;
  direction: string;
  strategy_type?: string;
  win_rate?: number;
  avg_score?: number;
  sample_size?: number;
}

export function RegimePerformanceView() {
  const [data, setData] = useState<RegimeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [computing, setComputing] = useState(false);

  const load = () => {
    setLoading(true);
    regimePerformanceService
      .get(90)
      .then((d) => setData(d.breakdown ?? []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const compute = async () => {
    setComputing(true);
    try {
      await regimePerformanceService.compute(90);
      load();
    } catch (e) {
      console.error(e);
    } finally {
      setComputing(false);
    }
  };

  const winRateColor = (wr?: number) => {
    if (wr == null) return "";
    if (wr >= 0.65) return "text-green-600 font-semibold";
    if (wr >= 0.5) return "text-yellow-600";
    return "text-red-600";
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Regime Performance</h1>
        <button
          className="bg-primary text-primary-foreground px-3 py-1 rounded text-sm disabled:opacity-50"
          onClick={compute}
          disabled={computing}
        >
          {computing ? "Computing…" : "Recompute"}
        </button>
      </div>

      <div className="rounded-lg border">
        {loading ? (
          <div className="p-4 text-sm text-muted-foreground">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left bg-muted/40">
                <th className="px-4 py-2">Regime</th>
                <th className="px-4 py-2">Direction</th>
                <th className="px-4 py-2">Strategy</th>
                <th className="px-4 py-2 text-right">Win Rate</th>
                <th className="px-4 py-2 text-right">Avg Score</th>
                <th className="px-4 py-2 text-right">Samples</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/20">
                  <td className="px-4 py-2">{row.regime}</td>
                  <td className="px-4 py-2">{row.direction}</td>
                  <td className="px-4 py-2 text-muted-foreground">{row.strategy_type ?? "—"}</td>
                  <td className={`px-4 py-2 text-right tabular-nums ${winRateColor(row.win_rate)}`}>
                    {row.win_rate != null ? `${(row.win_rate * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {row.avg_score != null ? row.avg_score.toFixed(1) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{row.sample_size ?? "—"}</td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-4 text-center text-muted-foreground">
                    No data — click Recompute to analyse historical signals
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
