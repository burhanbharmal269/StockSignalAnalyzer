"use client";

import { useQuery } from "@tanstack/react-query";
import { brokerService } from "@/services/broker.service";
import { AlertTriangle } from "lucide-react";
import Link from "next/link";

export function SessionWarningBanner() {
  const { data: status } = useQuery({
    queryKey: ["broker-status"],
    queryFn: brokerService.getStatus,
    refetchInterval: 30_000,
  });

  const { data: mode } = useQuery({
    queryKey: ["broker-mode"],
    queryFn: brokerService.getMode,
    refetchInterval: 30_000,
  });

  const isLive = mode?.mode === "LIVE";
  const sessionStatus = status?.session_status;
  const needsWarning =
    isLive &&
    (sessionStatus === "SESSION_EXPIRED" || sessionStatus === "AUTH_REQUIRED");

  if (!needsWarning) return null;

  const message =
    sessionStatus === "SESSION_EXPIRED"
      ? "Kite authentication expired. Live trading disabled until reconnection."
      : "Kite authentication required. Live trading is disabled.";

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-destructive/10 border-b border-destructive/30 text-sm text-destructive">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span className="flex-1">{message}</span>
      <Link
        href="/broker"
        className="font-medium underline underline-offset-2 hover:no-underline whitespace-nowrap"
      >
        Reconnect Kite →
      </Link>
    </div>
  );
}
