"use client";

import { useEffect, useState } from "react";
import { aiService } from "@/services/market.service";
import { Sparkles, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface MarketInsight {
  regime?: string;
  regime_confidence?: number;
  summary?: string;
  key_themes?: string[];
  risks?: string[];
  opportunities?: string[];
  recommendation?: string;
  generated_at?: string;
  message?: string;
  content?: unknown;
}

export function AIInsightsView() {
  const [insight, setInsight] = useState<MarketInsight | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  const loadInsight = () => {
    setLoading(true);
    aiService
      .getMarketInsight()
      .then((d) => {
        if (d?.content && typeof d.content === "string") {
          try { setInsight(JSON.parse(d.content)); } catch { setInsight(d); }
        } else {
          setInsight(d);
        }
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(loadInsight, []);

  const generate = async () => {
    setGenerating(true);
    try {
      const d = await aiService.generateInsight();
      setInsight(d);
    } catch (e) {
      console.error(e);
    } finally {
      setGenerating(false);
    }
  };

  const regimeBg = (r?: string) => {
    if (r === "BULLISH")  return "bg-green-100 text-green-800 border-green-300 dark:bg-green-950 dark:text-green-300";
    if (r === "BEARISH")  return "bg-red-100 text-red-800 border-red-300 dark:bg-red-950 dark:text-red-300";
    if (r === "VOLATILE") return "bg-orange-100 text-orange-800 border-orange-300 dark:bg-orange-950 dark:text-orange-300";
    return "bg-yellow-100 text-yellow-800 border-yellow-300 dark:bg-yellow-950 dark:text-yellow-300";
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-6 w-6 text-purple-500" />
          <h1 className="text-2xl font-bold">AI Market Insights</h1>
        </div>
        <button
          onClick={generate}
          disabled={generating}
          className="flex items-center gap-2 px-3 py-1.5 rounded-md border bg-card text-sm font-medium hover:bg-accent disabled:opacity-50"
        >
          <RefreshCw className={cn("h-4 w-4", generating && "animate-spin")} />
          {generating ? "Generating..." : "Generate New"}
        </button>
      </div>

      {loading && <p className="text-muted-foreground">Loading AI insights...</p>}

      {!loading && insight?.message === "no_insight_yet" && (
        <div className="rounded-md border p-6 text-center text-muted-foreground">
          No AI insights generated yet. Click &quot;Generate New&quot; to create one.
        </div>
      )}

      {!loading && insight && !insight.message && (
        <div className="space-y-4">
          {insight.regime && (
            <div className="flex items-center gap-3">
              <span className={cn("px-3 py-1 rounded-full text-sm font-semibold border", regimeBg(insight.regime))}>
                {insight.regime}
              </span>
              {insight.regime_confidence != null && (
                <span className="text-sm text-muted-foreground">
                  Confidence: {(insight.regime_confidence * 100).toFixed(0)}%
                </span>
              )}
            </div>
          )}

          {insight.summary && (
            <div className="rounded-md border p-4">
              <p className="text-xs font-medium text-muted-foreground mb-1 uppercase tracking-wide">Summary</p>
              <p className="text-base">{insight.summary}</p>
            </div>
          )}

          {insight.recommendation && (
            <div className="rounded-md border border-purple-300 bg-purple-50 dark:bg-purple-950/30 p-4">
              <p className="text-xs font-medium text-purple-700 dark:text-purple-300 mb-1 uppercase tracking-wide">Recommendation</p>
              <p className="text-base">{insight.recommendation}</p>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {(insight.key_themes ?? []).length > 0 && (
              <div className="rounded-md border p-4">
                <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Key Themes</p>
                <ul className="space-y-1">
                  {insight.key_themes!.map((t, i) => (
                    <li key={i} className="text-sm flex gap-1"><span className="text-blue-500">•</span>{t}</li>
                  ))}
                </ul>
              </div>
            )}
            {(insight.opportunities ?? []).length > 0 && (
              <div className="rounded-md border p-4">
                <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Opportunities</p>
                <ul className="space-y-1">
                  {insight.opportunities!.map((o, i) => (
                    <li key={i} className="text-sm flex gap-1"><span className="text-green-500">•</span>{o}</li>
                  ))}
                </ul>
              </div>
            )}
            {(insight.risks ?? []).length > 0 && (
              <div className="rounded-md border p-4">
                <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wide">Risks</p>
                <ul className="space-y-1">
                  {insight.risks!.map((r, i) => (
                    <li key={i} className="text-sm flex gap-1"><span className="text-red-500">•</span>{r}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {insight.generated_at && (
            <p className="text-xs text-muted-foreground">
              Generated: {new Date(insight.generated_at).toLocaleString()}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
