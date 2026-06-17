import { cn } from "@/lib/utils";
import type { ExecutionMode } from "@/types";

interface ExecutionModeBadgeProps {
  mode: ExecutionMode;
  ordersBlocked: boolean;
  className?: string;
}

export function ExecutionModeBadge({ mode, ordersBlocked, className }: ExecutionModeBadgeProps) {
  const isAutomatic = mode === "AUTOMATIC" && !ordersBlocked;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide border",
        isAutomatic
          ? "bg-orange-500/10 text-orange-500 border-orange-500/30"
          : "bg-muted text-muted-foreground border-border",
        className
      )}
    >
      {mode}
    </span>
  );
}

export function LiveDataBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide border",
        "bg-profit/10 text-profit border-profit/30",
        className
      )}
    >
      <span className="relative flex h-1.5 w-1.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-profit opacity-75" />
        <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-profit" />
      </span>
      LIVE DATA
    </span>
  );
}

// Backward-compatible wrapper for any code still using TradingModeBadge
export function TradingModeBadge({ mode, className }: { mode: string; className?: string }) {
  if (mode === "LIVE") {
    return <LiveDataBadge className={className} />;
  }
  return (
    <span className={cn("inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold border bg-muted text-muted-foreground border-border", className)}>
      {mode}
    </span>
  );
}
