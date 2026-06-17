import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

interface MetricTileProps {
  label: string;
  value: string | number;
  sub?: string;
  icon?: LucideIcon;
  trend?: "up" | "down" | "neutral";
  className?: string;
}

export function MetricTile({
  label,
  value,
  sub,
  icon: Icon,
  trend,
  className,
}: MetricTileProps) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-4 flex flex-col gap-2",
        className
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground font-medium uppercase tracking-wide">
          {label}
        </span>
        {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
      </div>
      <div
        className={cn(
          "text-2xl font-bold tabular-nums",
          trend === "up" && "text-profit",
          trend === "down" && "text-loss"
        )}
      >
        {value}
      </div>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}
