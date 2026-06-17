"use client";

import { useEffect, useState } from "react";
import { opportunitiesService } from "@/services/market.service";
import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface Opportunity {
  id: string | null;
  symbol: string;
  type: string;
  direction: string;
  total_score: number;
  confidence: number;
  technical_score: number;
  volume_score: number;
  sentiment_score: number;
  meta: Record<string, unknown>;
  created_at: string | null;
}

export function OpportunitiesView() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);

  const load = () => {
    setLoading(true);
    opportunitiesService
      .getOpportunities({ limit: 30 })
      .then((d) => setOpportunities(d.opportunities || []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const runScan = async () => {
    setScanning(true);
    try {
      await opportunitiesService.runScan("15m");
      load();
    } catch (e) {
      console.error(e);
    } finally {
      setScanning(false);
    }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Opportunities</h1>
        <button
          onClick={runScan}
          disabled={scanning}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md border bg-card text-sm font-medium hover:bg-accent disabled:opacity-50"
        >
          <RefreshCw className={cn("h-4 w-4", scanning && "animate-spin")} />
          {scanning ? "Scanning..." : "Run Scan"}
        </button>
      </div>

      {loading ? (
        <p className="text-muted-foreground">Loading opportunities...</p>
      ) : opportunities.length === 0 ? (
        <p className="text-muted-foreground">
          No opportunities found. Click &quot;Run Scan&quot; to scan the market.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                {["Symbol", "Type", "Direction", "Score", "Confidence", "Technical", "Volume", "Created"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium text-muted-foreground">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {opportunities.map((opp, i) => (
                <tr key={i} className="border-t hover:bg-muted/20">
                  <td className="px-3 py-2 font-mono font-semibold">{opp.symbol}</td>
                  <td className="px-3 py-2">
                    <span className="px-2 py-0.5 rounded border text-xs">{opp.type}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span className={cn("font-medium", opp.direction === "LONG" ? "text-green-500" : "text-red-500")}>
                      {opp.direction}
                    </span>
                  </td>
                  <td className="px-3 py-2">{opp.total_score.toFixed(1)}</td>
                  <td className="px-3 py-2">{(opp.confidence * 100).toFixed(0)}%</td>
                  <td className="px-3 py-2">{opp.technical_score.toFixed(1)}</td>
                  <td className="px-3 py-2">{opp.volume_score.toFixed(1)}</td>
                  <td className="px-3 py-2 text-muted-foreground text-xs">
                    {opp.created_at ? new Date(opp.created_at).toLocaleTimeString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
