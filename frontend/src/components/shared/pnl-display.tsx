import { cn, formatCurrency, formatPercent } from "@/lib/utils";

interface PnLDisplayProps {
  value: number;
  pct?: number;
  size?: "sm" | "md" | "lg";
  showSign?: boolean;
}

export function PnLDisplay({ value, pct, size = "md", showSign = true }: PnLDisplayProps) {
  const positive = value >= 0;
  const sizeClass = { sm: "text-sm", md: "text-base", lg: "text-xl font-bold" }[size];

  return (
    <span className={cn("tabular-nums font-medium", positive ? "text-profit" : "text-loss", sizeClass)}>
      {showSign && value > 0 && "+"}
      {formatCurrency(value)}
      {pct !== undefined && (
        <span className="ml-1 text-xs opacity-80">
          ({formatPercent(pct)})
        </span>
      )}
    </span>
  );
}
