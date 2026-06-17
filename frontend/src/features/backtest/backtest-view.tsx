"use client";

import { useEffect, useState } from "react";
import { backtestService } from "@/services/market.service";
import { MetricTile } from "@/components/shared/metric-tile";
import { cn } from "@/lib/utils";

const STRATEGIES = ["EMA_TREND", "VWAP_PULLBACK", "ORB", "MOMENTUM", "OI_STRATEGY", "REGIME_ADAPTIVE"];

interface RunSummary {
  run_id: string;
  strategy: string;
  symbol: string;
  timeframe: string;
  from_dt: string;
  to_dt: string;
  initial_capital: number;
  final_capital: number;
  win_rate: number;
  total_pnl: number;
  return_pct: number;
  max_drawdown_pct: number;
  profit_factor: number;
  total_trades: number;
}

export function BacktestView() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [lastResult, setLastResult] = useState<{ metrics?: Record<string, number> } | null>(null);

  const [strategy, setStrategy] = useState("EMA_TREND");
  const [symbol, setSymbol] = useState("NIFTY");
  const [timeframe, setTimeframe] = useState("D");
  const [fromDt, setFromDt] = useState("2024-01-01");
  const [toDt, setToDt] = useState(new Date().toISOString().slice(0, 10));
  const [capital, setCapital] = useState("100000");

  const loadRuns = () => {
    setLoading(true);
    backtestService
      .listRuns(20)
      .then((d) => setRuns(d.runs || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(loadRuns, []);

  const runBacktest = async () => {
    setRunning(true);
    setLastResult(null);
    try {
      const result = await backtestService.runBacktest({
        strategy,
        symbol: symbol.toUpperCase(),
        timeframe,
        from_dt: new Date(fromDt).toISOString(),
        to_dt: new Date(toDt).toISOString(),
        initial_capital: Number(capital),
      });
      setLastResult(result);
      loadRuns();
    } catch (e) {
      console.error(e);
    } finally {
      setRunning(false);
    }
  };

  const labelClass = "block text-xs text-muted-foreground mb-1";
  const inputClass = "w-full rounded-md border bg-background px-3 py-1.5 text-sm";

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Strategy Backtest</h1>

      <div className="rounded-md border p-4 space-y-4">
        <h2 className="font-semibold">Run New Backtest</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <div>
            <label className={labelClass}>Strategy</label>
            <select
              className={inputClass}
              value={strategy}
              onChange={(e) => setStrategy(e.target.value)}
            >
              {STRATEGIES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelClass}>Symbol</label>
            <input className={inputClass} value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          </div>
          <div>
            <label className={labelClass}>Timeframe</label>
            <input className={inputClass} value={timeframe} onChange={(e) => setTimeframe(e.target.value)} placeholder="D, 60m, 15m" />
          </div>
          <div>
            <label className={labelClass}>From Date</label>
            <input type="date" className={inputClass} value={fromDt} onChange={(e) => setFromDt(e.target.value)} />
          </div>
          <div>
            <label className={labelClass}>To Date</label>
            <input type="date" className={inputClass} value={toDt} onChange={(e) => setToDt(e.target.value)} />
          </div>
          <div>
            <label className={labelClass}>Capital (₹)</label>
            <input className={inputClass} value={capital} onChange={(e) => setCapital(e.target.value)} />
          </div>
        </div>
        <button
          onClick={runBacktest}
          disabled={running}
          className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
        >
          {running ? "Running..." : "Run Backtest"}
        </button>
      </div>

      {lastResult?.metrics && (
        <div className="rounded-md border p-4 space-y-3">
          <h2 className="font-semibold text-green-600">Latest Result</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {Object.entries(lastResult.metrics as Record<string, number>).map(([k, v]) => (
              <MetricTile key={k} label={k.replace(/_/g, " ")} value={typeof v === "number" ? v.toFixed(2) : String(v)} />
            ))}
          </div>
        </div>
      )}

      <h2 className="font-semibold">Recent Runs</h2>
      {loading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : runs.length === 0 ? (
        <p className="text-muted-foreground">No backtest runs yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                {["Strategy", "Symbol", "TF", "From", "To", "Trades", "Win%", "P&L", "Return%", "MaxDD%", "PF"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium text-muted-foreground">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="border-t hover:bg-muted/20">
                  <td className="px-3 py-2">
                    <span className="px-2 py-0.5 rounded border text-xs">{r.strategy}</span>
                  </td>
                  <td className="px-3 py-2 font-mono">{r.symbol}</td>
                  <td className="px-3 py-2">{r.timeframe}</td>
                  <td className="px-3 py-2 text-xs">{r.from_dt ? new Date(r.from_dt).toLocaleDateString() : "—"}</td>
                  <td className="px-3 py-2 text-xs">{r.to_dt ? new Date(r.to_dt).toLocaleDateString() : "—"}</td>
                  <td className="px-3 py-2">{r.total_trades ?? "—"}</td>
                  <td className="px-3 py-2">{r.win_rate != null ? `${r.win_rate.toFixed(1)}%` : "—"}</td>
                  <td className={cn("px-3 py-2 font-medium", (r.total_pnl ?? 0) >= 0 ? "text-green-500" : "text-red-500")}>
                    ₹{(r.total_pnl ?? 0).toLocaleString()}
                  </td>
                  <td className={cn("px-3 py-2", (r.return_pct ?? 0) >= 0 ? "text-green-500" : "text-red-500")}>
                    {r.return_pct != null ? `${r.return_pct.toFixed(2)}%` : "—"}
                  </td>
                  <td className="px-3 py-2 text-red-400">
                    {r.max_drawdown_pct != null ? `${r.max_drawdown_pct.toFixed(1)}%` : "—"}
                  </td>
                  <td className="px-3 py-2">{r.profit_factor != null ? r.profit_factor.toFixed(2) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
