"use client";

import { useEffect, useState } from "react";
import { symbolRankingService } from "@/services/research.service";

interface RankRow {
  rank?: number;
  ticker: string;
  signal_count?: number;
  win_rate?: number;
  avg_score?: number;
  avg_pnl?: number;
  composite_rank_score?: number;
}

export function SymbolRankingsView() {
  const [data, setData] = useState<RankRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [computing, setComputing] = useState(false);
  const [limit, setLimit] = useState(50);

  const load = () => {
    setLoading(true);
    symbolRankingService
      .get(limit)
      .then((d) => setData(d.rankings ?? []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(load, [limit]);

  const compute = async () => {
    setComputing(true);
    try {
      await symbolRankingService.compute(90);
      load();
    } catch (e) {
      console.error(e);
    } finally {
      setComputing(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Symbol Rankings</h1>
        <div className="flex gap-2 items-center">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            {[25, 50, 100, 200].map((n) => <option key={n} value={n}>Top {n}</option>)}
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
                <th className="px-4 py-2">#</th>
                <th className="px-4 py-2">Ticker</th>
                <th className="px-4 py-2 text-right">Signals</th>
                <th className="px-4 py-2 text-right">Win Rate</th>
                <th className="px-4 py-2 text-right">Avg Score</th>
                <th className="px-4 py-2 text-right">Avg P&L</th>
                <th className="px-4 py-2 text-right">Rank Score</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr key={i} className="border-b last:border-0 hover:bg-muted/20">
                  <td className="px-4 py-2 text-muted-foreground">{row.rank ?? i + 1}</td>
                  <td className="px-4 py-2 font-medium">{row.ticker}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{row.signal_count ?? "—"}</td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {row.win_rate != null ? `${(row.win_rate * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {row.avg_score != null ? row.avg_score.toFixed(1) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {row.avg_pnl != null ? row.avg_pnl.toFixed(2) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums font-medium">
                    {row.composite_rank_score != null ? row.composite_rank_score.toFixed(3) : "—"}
                  </td>
                </tr>
              ))}
              {data.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-4 text-center text-muted-foreground">
                    No rankings — click Recompute
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
