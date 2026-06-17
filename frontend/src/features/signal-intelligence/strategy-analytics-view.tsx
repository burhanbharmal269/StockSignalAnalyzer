"use client";

import { useState } from "react";
import { useStrategyLeaderboard } from "@/hooks/use-signal-intelligence";
import { cn } from "@/lib/utils";
import type { StrategyMetrics } from "@/services/signal-intelligence.service";

const LOOKBACK_OPTIONS = [7, 14, 30, 90];

const VERDICT_COLOR = {
  positive: "text-profit",
  negative: "text-loss",
  neutral: "text-muted-foreground",
};

function verdictColor(value: number): string {
  if (value > 0) return VERDICT_COLOR.positive;
  if (value < 0) return VERDICT_COLOR.negative;
  return VERDICT_COLOR.neutral;
}

function MetricRow({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="flex items-center justify-between py-1 border-b last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn("text-xs font-medium tabular-nums", className)}>{value}</span>
    </div>
  );
}

function ComponentBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground w-16 shrink-0">{label}</span>
      <div className="flex-1 bg-muted rounded-full h-1">
        <div className="bg-primary h-1 rounded-full" style={{ width: `${Math.min(value * 100, 100)}%` }} />
      </div>
      <span className="text-xs tabular-nums w-10 text-right">{(value * 100).toFixed(0)}%</span>
    </div>
  );
}

function StrategyCard({ metrics, isBest, isWorst }: { metrics: StrategyMetrics; isBest: boolean; isWorst: boolean }) {
  return (
    <div className={cn(
      "rounded-lg border bg-card p-4 space-y-3",
      isBest && "border-profit/50",
      isWorst && "border-loss/50",
    )}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">#{metrics.rank}</span>
          <span className="font-medium text-sm">{metrics.strategy_type}</span>
        </div>
        <div className="flex gap-1.5">
          {isBest && <span className="text-xs px-1.5 py-0.5 rounded bg-profit/10 text-profit">Best</span>}
          {isWorst && <span className="text-xs px-1.5 py-0.5 rounded bg-loss/10 text-loss">Worst</span>}
        </div>
      </div>

      <div className="space-y-0">
        <MetricRow label="Signals" value={`${metrics.signal_count} total / ${metrics.accepted_count} accepted`} />
        <MetricRow
          label="Win Rate"
          value={`${metrics.win_rate.toFixed(1)}%`}
          className={metrics.win_rate >= 50 ? "text-profit" : "text-loss"}
        />
        <MetricRow
          label="Profit Factor"
          value={metrics.profit_factor.toFixed(2)}
          className={verdictColor(metrics.profit_factor - 1)}
        />
        <MetricRow
          label="Sharpe Ratio"
          value={metrics.sharpe_ratio.toFixed(2)}
          className={verdictColor(metrics.sharpe_ratio)}
        />
        <MetricRow
          label="Avg Return"
          value={`${metrics.avg_return_pct >= 0 ? "+" : ""}${metrics.avg_return_pct.toFixed(2)}%`}
          className={verdictColor(metrics.avg_return_pct)}
        />
        <MetricRow
          label="Max Drawdown"
          value={`${metrics.max_drawdown_pct.toFixed(2)}%`}
          className="text-loss"
        />
        <MetricRow
          label="Expectancy"
          value={metrics.expectancy.toFixed(3)}
          className={verdictColor(metrics.expectancy)}
        />
        <MetricRow label="Avg Hold Time" value={`${metrics.avg_holding_time_minutes.toFixed(0)} min`} />
        <MetricRow label="Avg Score" value={metrics.avg_score.toFixed(1)} />
        <MetricRow label="Avg Confidence" value={`${metrics.avg_confidence.toFixed(1)}%`} />
      </div>

      <div>
        <p className="text-xs text-muted-foreground mb-2">Component Scores</p>
        <div className="space-y-1">
          <ComponentBar label="Trend" value={metrics.component_scores.trend} />
          <ComponentBar label="Volume" value={metrics.component_scores.volume} />
          <ComponentBar label="VWAP" value={metrics.component_scores.vwap} />
          <ComponentBar label="OI" value={metrics.component_scores.oi} />
          <ComponentBar label="Sentiment" value={metrics.component_scores.sentiment} />
        </div>
      </div>
    </div>
  );
}

export function StrategyAnalyticsView() {
  const [lookback, setLookback] = useState(30);
  const { data: leaderboard, isLoading } = useStrategyLeaderboard(lookback);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">Strategy Analytics</h1>
          <p className="text-sm text-muted-foreground">Performance leaderboard ranked by expectancy</p>
        </div>
        <div className="flex gap-1">
          {LOOKBACK_OPTIONS.map((d) => (
            <button
              key={d}
              onClick={() => setLookback(d)}
              className={cn(
                "text-xs px-2.5 py-1 rounded border",
                lookback === d
                  ? "bg-primary text-primary-foreground border-primary"
                  : "border-border hover:bg-muted"
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !leaderboard?.strategies.length ? (
        <div className="rounded-lg border bg-card p-8 text-center">
          <p className="text-sm text-muted-foreground">No strategy data yet.</p>
          <p className="text-xs text-muted-foreground mt-1">Requires at least 3 signals with outcome tracking per strategy.</p>
        </div>
      ) : (
        <>
          <div className="rounded-lg border bg-card p-4 flex gap-6">
            {leaderboard.best_strategy && (
              <div>
                <p className="text-xs text-muted-foreground">Best Strategy</p>
                <p className="text-sm font-medium text-profit">{leaderboard.best_strategy}</p>
              </div>
            )}
            {leaderboard.worst_strategy && (
              <div>
                <p className="text-xs text-muted-foreground">Worst Strategy</p>
                <p className="text-sm font-medium text-loss">{leaderboard.worst_strategy}</p>
              </div>
            )}
            <div>
              <p className="text-xs text-muted-foreground">Lookback</p>
              <p className="text-sm font-medium">{leaderboard.lookback_days} days</p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {leaderboard.strategies.map((m) => (
              <StrategyCard
                key={m.strategy_type}
                metrics={m}
                isBest={m.strategy_type === leaderboard.best_strategy}
                isWorst={m.strategy_type === leaderboard.worst_strategy}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
