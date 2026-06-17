"use client";

import { useEffect, useState } from "react";
import { paperDaemonService } from "@/services/market.service";
import { MetricTile } from "@/components/shared/metric-tile";
import { Play, Square, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface DaemonStatus {
  running: boolean;
  open_positions: number;
  capital: number;
  positions: string[];
  strategies: string[];
}

interface Performance {
  total_trades: number;
  total_pnl: number;
  win_rate: number;
  wins: number;
  losses: number;
  current_capital: number;
  initial_capital: number;
  return_pct: number;
}

interface JournalEntry {
  id: number;
  symbol: string;
  action: string;
  direction: string;
  price: number;
  qty: number;
  strategy_name: string;
  pnl: number | null;
  capital_after: number;
  ts: string;
}

export function PaperDaemonView() {
  const [status, setStatus] = useState<DaemonStatus | null>(null);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [toggling, setToggling] = useState(false);

  const load = () => {
    Promise.all([
      paperDaemonService.getStatus(),
      paperDaemonService.getPerformance(),
      paperDaemonService.getJournal(30),
    ])
      .then(([s, p, j]) => {
        setStatus(s);
        setPerf(p);
        setJournal(j.journal || []);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const toggle = async () => {
    setToggling(true);
    try {
      if (status?.running) {
        await paperDaemonService.stop();
      } else {
        await paperDaemonService.start();
      }
      load();
    } catch (e) {
      console.error(e);
    } finally {
      setToggling(false);
    }
  };

  const btnBase = "flex items-center gap-2 px-3 py-1.5 rounded-md border text-sm font-medium disabled:opacity-50";

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Paper Trading Daemon</h1>
        <div className="flex gap-2">
          <button onClick={load} className={cn(btnBase, "bg-card hover:bg-accent")}>
            <RefreshCw className="h-4 w-4" />
          </button>
          <button
            onClick={toggle}
            disabled={toggling || loading}
            className={cn(
              btnBase,
              status?.running
                ? "bg-red-600 text-white border-red-600 hover:bg-red-700"
                : "bg-primary text-primary-foreground border-primary hover:bg-primary/90"
            )}
          >
            {status?.running ? (
              <><Square className="h-4 w-4" />Stop</>
            ) : (
              <><Play className="h-4 w-4" />Start</>
            )}
          </button>
        </div>
      </div>

      {loading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : (
        <>
          <div className="flex items-center gap-3 flex-wrap">
            <span
              className={cn(
                "px-3 py-1 rounded-full text-xs font-semibold border",
                status?.running
                  ? "bg-green-100 text-green-800 border-green-300 dark:bg-green-950 dark:text-green-300"
                  : "bg-muted text-muted-foreground border-border"
              )}
            >
              {status?.running ? "RUNNING" : "STOPPED"}
            </span>
            {status?.strategies && status.strategies.length > 0 && (
              <span className="text-sm text-muted-foreground">
                Strategies: {status.strategies.join(", ")}
              </span>
            )}
          </div>

          {perf && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricTile label="Current Capital" value={`₹${perf.current_capital.toLocaleString()}`} />
              <MetricTile
                label="Total P&L"
                value={`₹${perf.total_pnl.toLocaleString()}`}
                trend={perf.total_pnl >= 0 ? "up" : "down"}
              />
              <MetricTile
                label="Return"
                value={`${perf.return_pct.toFixed(2)}%`}
                trend={perf.return_pct >= 0 ? "up" : "down"}
              />
              <MetricTile label="Win Rate" value={`${perf.win_rate.toFixed(1)}%`} />
              <MetricTile label="Total Trades" value={perf.total_trades} />
              <MetricTile label="Wins" value={perf.wins} />
              <MetricTile label="Losses" value={perf.losses} />
              <MetricTile label="Open Positions" value={status?.open_positions ?? 0} />
            </div>
          )}

          {status?.positions && status.positions.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold mb-2">Open Positions</h2>
              <div className="flex flex-wrap gap-2">
                {status.positions.map((p) => (
                  <span key={p} className="px-2 py-0.5 rounded border text-xs font-mono">{p}</span>
                ))}
              </div>
            </div>
          )}

          <h2 className="font-semibold">Trade Journal</h2>
          {journal.length === 0 ? (
            <p className="text-muted-foreground text-sm">No trades recorded yet.</p>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr>
                    {["Time", "Symbol", "Action", "Direction", "Price", "Qty", "Strategy", "P&L", "Capital"].map((h) => (
                      <th key={h} className="px-3 py-2 text-left font-medium text-muted-foreground">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {journal.map((e) => (
                    <tr key={e.id} className="border-t hover:bg-muted/20">
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {new Date(e.ts).toLocaleTimeString()}
                      </td>
                      <td className="px-3 py-2 font-mono font-semibold">{e.symbol}</td>
                      <td className="px-3 py-2">
                        <span className="px-2 py-0.5 rounded border text-xs">{e.action}</span>
                      </td>
                      <td className={cn("px-3 py-2 font-medium", e.direction === "LONG" ? "text-green-500" : "text-red-500")}>
                        {e.direction}
                      </td>
                      <td className="px-3 py-2">₹{e.price.toLocaleString()}</td>
                      <td className="px-3 py-2">{e.qty}</td>
                      <td className="px-3 py-2 text-xs">{e.strategy_name}</td>
                      <td className={cn("px-3 py-2 font-medium", (e.pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500")}>
                        {e.pnl != null ? `₹${e.pnl.toLocaleString()}` : "—"}
                      </td>
                      <td className="px-3 py-2">₹{e.capital_after.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
