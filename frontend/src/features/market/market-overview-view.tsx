"use client";

import { useEffect, useRef, useState } from "react";
import { marketService, newsService } from "@/services/market.service";
import { MetricTile } from "@/components/shared/metric-tile";
import { TrendingUp, TrendingDown, Minus, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMarketOpen } from "@/hooks/use-market-open";

interface Breadth {
  advances: number;
  declines: number;
  unchanged: number;
  advance_decline_ratio: number;
  breadth_score: number;
  above_200dma_pct: number;
  new_highs_52w: number;
  new_lows_52w: number;
}

interface Sentiment {
  avg_score: number;
  direction: string;
  total_articles: number;
  bullish: number;
  bearish: number;
  neutral: number;
}

export function MarketOverviewView() {
  const [breadth, setBreadth] = useState<Breadth | null>(null);
  const [sentiment, setSentiment] = useState<Sentiment | null>(null);
  const [loading, setLoading] = useState(true);
  const { marketOpen, session } = useMarketOpen();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = () => {
    Promise.all([marketService.getBreadth(), newsService.getMarketSentiment()])
      .then(([b, s]) => {
        setBreadth(b?.advances != null ? b : null);
        setSentiment(s?.avg_score != null ? s : null);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchData();
    // Auto-refresh every 5 minutes only during market hours
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (marketOpen) {
      intervalRef.current = setInterval(fetchData, 5 * 60_000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [marketOpen]);

  if (loading) return <div className="p-6 text-muted-foreground">Loading market overview...</div>;

  const adTrend =
    breadth && breadth.advance_decline_ratio > 1.2
      ? "up"
      : breadth && breadth.advance_decline_ratio < 0.8
      ? "down"
      : "neutral";

  const sentDir = sentiment?.direction;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">Market Overview</h1>
        <span
          className={cn(
            "text-xs font-semibold px-2 py-0.5 rounded-full",
            session === "open"
              ? "bg-green-100 text-green-800"
              : session === "pre-open"
              ? "bg-yellow-100 text-yellow-800"
              : "bg-muted text-muted-foreground",
          )}
        >
          {session === "open" ? "Market Open" : session === "pre-open" ? "Pre-Open" : "Market Closed"}
        </span>
      </div>

      {breadth ? (
        <>
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">Market Breadth</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricTile label="Advances" value={breadth.advances} icon={TrendingUp} trend="up" />
            <MetricTile label="Declines" value={breadth.declines} icon={TrendingDown} trend="down" />
            <MetricTile label="A/D Ratio" value={breadth.advance_decline_ratio.toFixed(2)} trend={adTrend} />
            <MetricTile label="Breadth Score" value={`${breadth.breadth_score.toFixed(1)}%`} trend={adTrend} />
            <MetricTile label="Above 200 DMA" value={`${breadth.above_200dma_pct.toFixed(1)}%`} icon={Activity} />
            <MetricTile label="52W Highs" value={breadth.new_highs_52w} />
            <MetricTile label="52W Lows" value={breadth.new_lows_52w} />
            <MetricTile label="Unchanged" value={breadth.unchanged} icon={Minus} />
          </div>
        </>
      ) : (
        <div className="rounded-md border p-4 text-muted-foreground text-sm">
          No breadth data yet. The system collects breadth data during market hours.
        </div>
      )}

      {sentiment ? (
        <>
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mt-2">Market Sentiment</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <MetricTile
              label="Overall Direction"
              value={sentDir ?? "NEUTRAL"}
              trend={sentDir === "BULLISH" ? "up" : sentDir === "BEARISH" ? "down" : "neutral"}
            />
            <MetricTile label="Avg Score" value={sentiment.avg_score.toFixed(3)} />
            <MetricTile label="Total Articles" value={sentiment.total_articles} />
            <MetricTile label="Bullish" value={sentiment.bullish} trend="up" />
            <MetricTile label="Bearish" value={sentiment.bearish} trend="down" />
            <MetricTile label="Neutral" value={sentiment.neutral} />
          </div>
        </>
      ) : (
        <div className="rounded-md border p-4 text-muted-foreground text-sm">
          No sentiment data yet. Run &quot;News Refresh&quot; from the News section to populate.
        </div>
      )}
    </div>
  );
}
