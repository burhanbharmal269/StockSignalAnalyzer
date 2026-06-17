"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { brokerService } from "@/services/broker.service";
import { executionService } from "@/services/execution.service";
import { StatusIndicator } from "@/components/shared/status-indicator";
import { formatDateTime } from "@/lib/utils";
import { toast } from "sonner";
import {
  Activity, AlertTriangle, ExternalLink, Lock, LogIn, Server, ShieldAlert, Unlock, User,
} from "lucide-react";
import { useWebSocket } from "@/hooks/use-websocket";
import { useCallback } from "react";
import type { BrokerSessionResponse, BrokerStatus, ExecutionMode, WSEvent } from "@/types";

const EXECUTION_MODES: ExecutionMode[] = ["MANUAL", "AUTOMATIC"];

export function BrokerView() {
  const qc = useQueryClient();
  const [modeChangePending, setModeChangePending] = useState<ExecutionMode | null>(null);

  const { data: status, isLoading } = useQuery({
    queryKey: ["broker-status"],
    queryFn: brokerService.getStatus,
    refetchInterval: 10_000,
  });

  const { data: executionStatus, refetch: refetchExecution } = useQuery({
    queryKey: ["execution-status"],
    queryFn: executionService.getStatus,
    refetchInterval: 10_000,
  });

  const { data: sessionData, refetch: refetchSession } = useQuery<BrokerSessionResponse>({
    queryKey: ["broker-session"],
    queryFn: brokerService.getSession,
    refetchInterval: 30_000,
  });

  const lockExecution = useMutation({
    mutationFn: (note: string) => executionService.lock(note),
    onSuccess: () => {
      toast.warning("Execution LOCKED — orders halted, signals continue");
      refetchExecution();
    },
  });

  const unlockExecution = useMutation({
    mutationFn: (note: string) => executionService.unlock(note),
    onSuccess: () => {
      toast.success("Execution UNLOCKED");
      refetchExecution();
    },
  });

  const setMode = useMutation({
    mutationFn: (mode: ExecutionMode) => executionService.setMode(mode),
    onSuccess: (data) => {
      toast.success(`Execution mode → ${data.execution_mode}`);
      refetchExecution();
      setModeChangePending(null);
    },
    onError: () => {
      toast.error("Failed to change execution mode");
      setModeChangePending(null);
    },
  });

  const loginMutation = useMutation({
    mutationFn: brokerService.getLoginUrl,
    onSuccess: (data) => {
      window.location.href = data.login_url;
    },
    onError: () => toast.error("Failed to get login URL. Check KITE_API_KEY in .env."),
  });

  const wsHandler = useCallback(
    (_event: WSEvent<BrokerStatus>) => {
      qc.invalidateQueries({ queryKey: ["broker-status"] });
      qc.invalidateQueries({ queryKey: ["broker-session"] });
    },
    [qc]
  );
  useWebSocket<BrokerStatus>("broker.status", wsHandler);

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!status) return <p className="text-sm text-muted-foreground">No broker data</p>;

  const isHealthy = status.status === "HEALTHY";
  const sessionStatus = status.session_status;
  const session = sessionData?.session ?? null;
  const hasActiveSession = sessionStatus === "CONNECTED";

  const isLocked = executionStatus?.locked ?? false;
  const currentMode = (executionStatus?.execution_mode ?? "MANUAL") as ExecutionMode;
  const ordersBlocked = executionStatus?.orders_blocked ?? true;

  const sessionStatusLabel: Record<string, { label: string; cls: string }> = {
    CONNECTED: { label: "Connected", cls: "bg-green-100 text-green-800 border-green-300 dark:bg-green-950 dark:text-green-300" },
    DISCONNECTED: { label: "Disconnected", cls: "bg-muted text-muted-foreground border-border" },
    AUTH_REQUIRED: { label: "Authentication Required", cls: "bg-yellow-100 text-yellow-800 border-yellow-300 dark:bg-yellow-950 dark:text-yellow-300" },
    SESSION_EXPIRED: { label: "Session Expired", cls: "bg-destructive/10 text-destructive border-destructive/30" },
    ERROR: { label: "Error", cls: "bg-destructive/10 text-destructive border-destructive/30" },
  };
  const ssInfo = sessionStatusLabel[sessionStatus] ?? sessionStatusLabel.DISCONNECTED;

  const capStatus = (s: string) =>
    s === "OK" ? "text-green-600" : s === "DEGRADED" ? "text-yellow-600" : "text-red-500";

  return (
    <div className="space-y-6">
      {/* Status badges */}
      <div className="flex items-center gap-4 flex-wrap">
        <StatusIndicator
          status={isHealthy ? "healthy" : "unhealthy"}
          label={isHealthy ? "Connected" : status.status}
        />
        <span className="inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-xs font-semibold border bg-profit/10 text-profit border-profit/30">
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-profit opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-profit" />
          </span>
          LIVE DATA
        </span>
        {isLocked && (
          <span className="text-xs font-semibold bg-warning/10 text-warning border border-warning/30 rounded px-2 py-0.5">
            EXECUTION LOCKED
          </span>
        )}
        {currentMode === "AUTOMATIC" && !ordersBlocked && (
          <span className="text-xs font-semibold bg-orange-500/10 text-orange-500 border border-orange-500/30 rounded px-2 py-0.5">
            AUTO EXECUTE
          </span>
        )}
      </div>

      {/* AUTOMATIC mode warning */}
      {currentMode === "AUTOMATIC" && !ordersBlocked && (
        <div className="flex items-start gap-3 rounded-lg border border-orange-300 bg-orange-50 dark:bg-orange-950/20 p-4 text-sm text-orange-700 dark:text-orange-300">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <p className="font-semibold">AUTOMATIC MODE — Signals trigger real orders</p>
            <p className="text-xs mt-0.5 opacity-80">
              Orders will be submitted to Kite Connect automatically. Lock execution to stop order placement without stopping signal generation.
            </p>
          </div>
        </div>
      )}

      {/* Broker status card */}
      <div className="rounded-lg border bg-card p-4 space-y-4">
        <div className="flex items-center gap-2">
          <Server className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-medium">Broker Status</h2>
        </div>

        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${ssInfo.cls}`}>
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          {ssInfo.label}
        </span>

        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
          <div>
            <span className="text-muted-foreground text-xs block">Broker</span>
            <span className="font-medium capitalize">{status.broker_name}</span>
          </div>
          <div>
            <span className="text-muted-foreground text-xs block">Health</span>
            <span className={isHealthy ? "font-medium text-green-600" : "font-medium text-red-500"}>
              {status.status}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground text-xs block">Latency</span>
            <span className="font-medium tabular-nums">{status.latency_ms.toFixed(2)}ms</span>
          </div>
          {status.authenticated_user && (
            <div>
              <span className="text-muted-foreground text-xs block">Authenticated As</span>
              <span className="font-medium flex items-center gap-1">
                <User className="h-3 w-3" />{status.authenticated_user}
              </span>
            </div>
          )}
          {status.session_created_at && (
            <div>
              <span className="text-muted-foreground text-xs block">Session Created</span>
              <span className="font-medium">{formatDateTime(status.session_created_at)}</span>
            </div>
          )}
          {status.session_expires_at && (
            <div>
              <span className="text-muted-foreground text-xs block">Session Expires</span>
              <span className={`font-medium ${sessionStatus === "SESSION_EXPIRED" ? "text-red-500" : ""}`}>
                {formatDateTime(status.session_expires_at)}
              </span>
            </div>
          )}
        </div>

        <div className="border-t pt-3 grid grid-cols-3 gap-2 text-xs">
          <div>
            <span className="text-muted-foreground block">Market Data</span>
            <span className={`font-semibold flex items-center gap-1 ${capStatus(status.market_data_status)}`}>
              <Activity className="h-3 w-3" />{status.market_data_status}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground block">Order Placement</span>
            <span className={`font-semibold ${capStatus(status.order_placement_status)}`}>
              {status.order_placement_status}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground block">Historical Data</span>
            <span className={`font-semibold ${capStatus(status.historical_data_status)}`}>
              {status.historical_data_status}
            </span>
          </div>
        </div>

        <div className="text-xs text-muted-foreground border-t pt-2">
          Last validated: {formatDateTime(status.checked_at)}
        </div>
      </div>

      {/* Kite session panel — always shown (live data always required) */}
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2">
          <LogIn className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-medium">Kite Session</h2>
        </div>

        {hasActiveSession && session ? (
          <div className="space-y-2 text-sm">
            <StatusIndicator status="active" label="Session active" />
            <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground pt-1">
              <div>
                <span className="block">Session ID</span>
                <span className="font-mono text-foreground">{session!.session_id.slice(0, 8)}…</span>
              </div>
              <div>
                <span className="block">Expires at</span>
                <span className="font-medium text-foreground">{formatDateTime(session!.expires_at)}</span>
              </div>
              <div>
                <span className="block">Connected at</span>
                <span className="font-medium text-foreground">{formatDateTime(session!.created_at)}</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-start gap-2 p-3 rounded bg-warning/10 border border-warning/30 text-sm text-warning">
              <ShieldAlert className="h-4 w-4 mt-0.5 shrink-0" />
              <span>
                No active Kite session. Live market data and orders require authentication.
              </span>
            </div>
            <button
              onClick={() => loginMutation.mutate()}
              disabled={loginMutation.isPending}
              className="flex items-center gap-2 px-3 py-1.5 text-sm rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              {loginMutation.isPending ? "Opening…" : "Connect to Kite"}
            </button>
            <KiteTokenInput onSubmit={async (token) => {
              try {
                await brokerService.submitCallback(token);
                toast.success("Kite session activated successfully");
                refetchSession();
                qc.invalidateQueries({ queryKey: ["broker-status"] });
              } catch (err: unknown) {
                const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Check the request_token.";
                toast.error(`Kite auth failed: ${msg}`);
              }
            }} />
          </div>
        )}
      </div>

      {/* Execution Mode */}
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <h2 className="text-sm font-medium">Execution Mode</h2>
        <p className="text-xs text-muted-foreground">
          Current mode: <strong>{currentMode}</strong>. Signal generation, storage, and analytics always run regardless.
        </p>
        <div className="grid grid-cols-2 gap-3">
          {EXECUTION_MODES.map((mode) => (
            <button
              key={mode}
              onClick={() => setModeChangePending(mode)}
              disabled={currentMode === mode || setMode.isPending}
              className={`px-3 py-2 text-sm rounded border text-left disabled:opacity-50 ${
                currentMode === mode
                  ? "bg-primary/10 border-primary text-primary font-medium"
                  : "border-border hover:bg-accent"
              }`}
            >
              <span className="block font-medium">{mode}</span>
              <span className="block text-xs text-muted-foreground mt-0.5">
                {mode === "MANUAL"
                  ? "Signals stored. You place trades manually."
                  : "Signals trigger orders automatically via Kite."}
              </span>
            </button>
          ))}
        </div>
        {modeChangePending && modeChangePending !== currentMode && (
          <div className="rounded border border-orange-300 bg-orange-50 dark:bg-orange-950/20 p-3 space-y-2 text-sm">
            {modeChangePending === "AUTOMATIC" && (
              <p className="text-orange-700 dark:text-orange-300 text-xs">
                <strong>Warning:</strong> AUTOMATIC mode will submit real orders to Kite Connect. Ensure your Kite session is active.
              </p>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => setMode.mutate(modeChangePending)}
                disabled={setMode.isPending}
                className="px-3 py-1 text-sm rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {setMode.isPending ? "Changing…" : `Confirm → ${modeChangePending}`}
              </button>
              <button
                onClick={() => setModeChangePending(null)}
                className="px-3 py-1 text-sm rounded border hover:bg-muted"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Execution Lock */}
      <div className="rounded-lg border bg-card p-4 space-y-3">
        <h2 className="text-sm font-medium">Execution Lock</h2>
        <p className="text-xs text-muted-foreground">
          The execution lock gates order placement without stopping signal generation. Signals, analytics, and dashboards always continue.
        </p>
        {isLocked ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-warning text-sm">
              <Lock className="h-4 w-4" />
              <span className="font-semibold">LOCKED — orders halted</span>
            </div>
            {executionStatus?.changed_at && (
              <p className="text-xs text-muted-foreground">
                Locked {formatDateTime(executionStatus.changed_at)} by {executionStatus.changed_by ?? "unknown"}
                {executionStatus.note ? ` — ${executionStatus.note}` : ""}
              </p>
            )}
            <button
              onClick={() => unlockExecution.mutate("Manually unlocked from broker view")}
              disabled={unlockExecution.isPending}
              className="px-3 py-1.5 text-sm rounded bg-profit/10 text-profit border border-profit/30 hover:bg-profit/20 disabled:opacity-50 flex items-center gap-1.5"
            >
              <Unlock className="h-3.5 w-3.5" />
              {unlockExecution.isPending ? "Unlocking…" : "Unlock Execution"}
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-profit text-sm">
              <Unlock className="h-4 w-4" />
              <span className="font-semibold">UNLOCKED</span>
            </div>
            <p className="text-xs text-muted-foreground">
              {currentMode === "AUTOMATIC"
                ? "Orders will be submitted to Kite automatically."
                : "No orders placed (MANUAL mode — switch mode above to enable auto-execution)."}
            </p>
            {currentMode === "AUTOMATIC" && (
              <button
                onClick={() => lockExecution.mutate("Emergency lock from broker view")}
                disabled={lockExecution.isPending}
                className="px-3 py-1.5 text-sm rounded bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20 disabled:opacity-50 flex items-center gap-1.5"
              >
                <Lock className="h-3.5 w-3.5" />
                {lockExecution.isPending ? "Locking…" : "Lock Execution"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function KiteTokenInput({ onSubmit }: { onSubmit: (token: string) => Promise<void> }) {
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!token.trim()) return;
    setSubmitting(true);
    try {
      await onSubmit(token.trim());
      setToken("");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-1.5">
      <p className="text-xs text-muted-foreground">Or paste the request_token from the Kite redirect URL:</p>
      <div className="flex gap-2">
        <input
          type="text"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="request_token"
          className="flex-1 text-sm px-2.5 py-1.5 rounded border bg-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <button
          onClick={handleSubmit}
          disabled={!token.trim() || submitting}
          className="px-3 py-1.5 text-sm rounded bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {submitting ? "…" : "Submit"}
        </button>
      </div>
    </div>
  );
}
