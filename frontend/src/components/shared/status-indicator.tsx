import { cn } from "@/lib/utils";

interface StatusIndicatorProps {
  status: "healthy" | "degraded" | "unhealthy" | "active" | "inactive" | "unknown";
  label?: string;
  size?: "sm" | "md";
}

const STATUS_CONFIG = {
  healthy: { dot: "bg-profit", text: "text-profit", label: "Healthy" },
  active: { dot: "bg-profit", text: "text-profit", label: "Active" },
  degraded: { dot: "bg-warning", text: "text-warning", label: "Degraded" },
  unhealthy: { dot: "bg-loss", text: "text-loss", label: "Unhealthy" },
  inactive: { dot: "bg-muted-foreground", text: "text-muted-foreground", label: "Inactive" },
  unknown: { dot: "bg-muted-foreground", text: "text-muted-foreground", label: "Unknown" },
} as const;

export function StatusIndicator({ status, label, size = "md" }: StatusIndicatorProps) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.unknown;
  return (
    <div className="flex items-center gap-1.5">
      <span
        className={cn(
          "rounded-full shrink-0",
          config.dot,
          size === "sm" ? "h-1.5 w-1.5" : "h-2 w-2"
        )}
      />
      <span
        className={cn(
          config.text,
          size === "sm" ? "text-xs" : "text-sm"
        )}
      >
        {label ?? config.label}
      </span>
    </div>
  );
}
