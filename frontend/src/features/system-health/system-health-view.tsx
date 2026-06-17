"use client";

import { useQuery } from "@tanstack/react-query";
import { healthService } from "@/services/health.service";
import { StatusIndicator } from "@/components/shared/status-indicator";
import type { HealthStatus } from "@/types";

function mapStatus(raw: string): "healthy" | "degraded" | "unhealthy" {
  if (raw === "ok") return "healthy";
  if (raw === "degraded") return "degraded";
  return "unhealthy";
}

export function SystemHealthView() {
  const { data: health, isLoading, isError } = useQuery<HealthStatus>({
    queryKey: ["health"],
    queryFn: healthService.get,
    refetchInterval: 15_000,
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (isError || !health) {
    return <p className="text-sm text-destructive">Health check unavailable</p>;
  }

  const displayStatus = mapStatus(health.status);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <StatusIndicator status={displayStatus} />
        <div className="space-y-0.5">
          <p className="text-sm font-medium capitalize">{displayStatus}</p>
          <p className="text-xs text-muted-foreground">
            v{health.version ?? "—"} · {health.environment ?? "unknown"}
          </p>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-4 text-sm text-muted-foreground">
        Full component health reporting requires backend observability extension.
      </div>
    </div>
  );
}
