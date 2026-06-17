"use client";

import { useEffect, useState } from "react";
import { optionService } from "@/services/market.service";
import { MetricTile } from "@/components/shared/metric-tile";
import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface OCSummary {
  underlying?: string;
  pcr?: number;
  max_pain?: number;
  total_call_oi?: number;
  total_put_oi?: number;
  dominant_pattern?: string;
  ts?: string;
  message?: string;
}

export function OptionChainView() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [input, setInput] = useState("NIFTY");
  const [data, setData] = useState<OCSummary | null>(null);
  const [loading, setLoading] = useState(false);

  const load = (sym: string) => {
    setLoading(true);
    optionService
      .getChain(sym)
      .then((d) => setData(d))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => load(underlying), [underlying]);

  const refresh = async () => {
    try {
      await optionService.refresh(underlying);
      load(underlying);
    } catch (e) {
      console.error(e);
    }
  };

  const pcrColor =
    data?.pcr != null
      ? data.pcr > 1.3
        ? "text-green-500"
        : data.pcr < 0.7
        ? "text-red-500"
        : "text-yellow-500"
      : "";

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <h1 className="text-2xl font-bold">Option Chain</h1>
        <input
          className="w-28 rounded-md border bg-background px-3 py-1.5 text-sm"
          value={input}
          onChange={(e) => setInput(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && setUnderlying(input)}
          placeholder="Symbol"
        />
        <button
          onClick={() => setUnderlying(input)}
          className="px-3 py-1.5 rounded-md border bg-card text-sm font-medium hover:bg-accent"
        >
          Load
        </button>
        <button
          onClick={refresh}
          disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md border bg-card text-sm font-medium hover:bg-accent disabled:opacity-50"
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {loading && <p className="text-muted-foreground">Loading option chain...</p>}

      {data && !data.message && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricTile
              label="PCR"
              value={data.pcr != null ? data.pcr.toFixed(3) : "—"}
              className={pcrColor}
            />
            <MetricTile
              label="Max Pain"
              value={data.max_pain != null ? data.max_pain.toLocaleString() : "—"}
            />
            <MetricTile
              label="Total Call OI"
              value={data.total_call_oi != null ? (data.total_call_oi / 1e6).toFixed(2) + "M" : "—"}
            />
            <MetricTile
              label="Total Put OI"
              value={data.total_put_oi != null ? (data.total_put_oi / 1e6).toFixed(2) + "M" : "—"}
            />
          </div>

          {data.dominant_pattern && (
            <div className="rounded-md border p-4">
              <p className="text-sm font-medium text-muted-foreground">Dominant OI Pattern</p>
              <p className="text-lg font-semibold mt-1">{data.dominant_pattern}</p>
            </div>
          )}

          {data.ts && (
            <p className="text-xs text-muted-foreground">
              Last updated: {new Date(data.ts).toLocaleString()}
            </p>
          )}
        </>
      )}

      {data?.message && (
        <p className="text-muted-foreground">
          No option chain data for {underlying}. Click Refresh to fetch.
        </p>
      )}
    </div>
  );
}
