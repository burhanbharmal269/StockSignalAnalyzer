"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { operationsService } from "@/services/operations.service";
import type {
  ComponentStatus,
  Incident,
  PlatformReadiness,
  PreMarketCheck,
  ScanCycleMetric,
} from "@/services/operations.service";
import { cn } from "@/lib/utils";

// ─── Helpers ─────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  READY:     "text-profit bg-profit/10 border-profit/30",
  WARNING:   "text-warning bg-warning/10 border-warning/30",
  NOT_READY: "text-loss bg-loss/10 border-loss/30",
  UNKNOWN:   "text-muted-foreground bg-muted/20 border-border",
};

const SEVERITY_STYLES: Record<string, string> = {
  CRITICAL: "text-loss bg-loss/10 border-loss/30",
  HIGH:     "text-orange-400 bg-orange-400/10 border-orange-400/30",
  MEDIUM:   "text-warning bg-warning/10 border-warning/30",
  LOW:      "text-muted-foreground bg-muted/20 border-border",
};

const COMPONENT_LABELS: Record<string, string> = {
  database:           "Database",
  redis:              "Redis",
  kite:               "Kite Auth",
  market_data:        "Market Data",
  websocket:          "WebSocket",
  scanner:            "Scanner",
  background_tasks:   "Background Tasks",
  option_chain:       "Option Chain",
  data_quality:       "Data Quality",
  execution_quality:  "Execution Quality",
  deployment_stage:   "Deployment Stage",
  architecture_freeze:"Architecture Freeze",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium",
        STATUS_STYLES[status] ?? STATUS_STYLES.UNKNOWN,
      )}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium",
        SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.LOW,
      )}
    >
      {severity}
    </span>
  );
}

function BoolDot({ ok }: { ok: boolean }) {
  return (
    <span className={cn("inline-block h-2 w-2 rounded-full", ok ? "bg-profit" : "bg-loss")} />
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="mb-3 text-sm font-semibold text-muted-foreground uppercase tracking-wide">
        {title}
      </h3>
      {children}
    </div>
  );
}

// ─── Tab: Readiness ───────────────────────────────────────────────────────────

function ReadinessTab() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["platform-readiness"],
    queryFn: operationsService.getReadiness,
    refetchInterval: 30_000,
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (error || !data) return <p className="text-sm text-loss">Failed to load readiness data.</p>;

  const comps = data.components;

  return (
    <div className="space-y-4">
      {/* Overall banner */}
      <div
        className={cn(
          "flex items-center justify-between rounded-lg border p-4",
          STATUS_STYLES[data.overall],
        )}
      >
        <div>
          <div className="text-lg font-bold">{data.overall.replace("_", " ")}</div>
          <div className="mt-1 text-sm opacity-80">{data.recommendation}</div>
        </div>
        <div className="text-right">
          <StatusBadge status={data.overall} />
          <div className="mt-1 text-xs text-muted-foreground">
            {new Date(data.checked_at).toLocaleTimeString()}
          </div>
        </div>
      </div>

      <button
        onClick={() => refetch()}
        className="text-xs text-primary hover:underline"
      >
        Refresh
      </button>

      {/* Component grid */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(comps).map(([key, comp]) => (
          <ComponentCard key={key} name={key} data={comp} />
        ))}
      </div>
    </div>
  );
}

function ComponentCard({ name, data }: { name: string; data: ComponentStatus }) {
  const [expanded, setExpanded] = useState(false);
  const { status, ...rest } = data;
  const label = COMPONENT_LABELS[name] ?? name;
  const detail = (rest as any).detail as string | undefined;

  return (
    <div
      className={cn(
        "cursor-pointer rounded-lg border p-3 transition-all hover:shadow-sm",
        status === "READY"     ? "border-profit/30 bg-profit/5"    :
        status === "WARNING"   ? "border-warning/30 bg-warning/5"  :
                                  "border-loss/30 bg-loss/5",
      )}
      onClick={() => setExpanded((e) => !e)}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <StatusBadge status={status} />
      </div>
      {detail && <p className="mt-1.5 text-xs text-muted-foreground">{detail}</p>}
      {expanded && (
        <pre className="mt-2 overflow-auto rounded bg-muted/30 p-2 text-xs text-muted-foreground">
          {JSON.stringify(rest, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ─── Tab: Incidents ───────────────────────────────────────────────────────────

const INCIDENT_TYPES = [
  "KITE_AUTH_EXPIRED", "SCANNER_IDLE", "MARKET_DATA_STALE",
  "REDIS_DISCONNECTED", "DB_CONNECTION_LOST", "EXECUTION_HALTED",
  "KILL_SWITCH_TRIGGERED", "OPTION_CHAIN_STALE", "SIGNAL_GATE_FAILURE",
  "VIX_SPIKE", "RISK_BREACH", "WEBSOCKET_DISCONNECTED",
];

function IncidentsTab() {
  const qc = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [resolveId, setResolveId] = useState<number | null>(null);
  const [resolution, setResolution] = useState("");
  const [newInc, setNewInc] = useState({
    incident_type: INCIDENT_TYPES[0],
    severity: "HIGH",
    title: "",
    root_cause: "",
    impact: "",
  });

  const { data: summary } = useQuery({
    queryKey: ["incident-summary"],
    queryFn: operationsService.getIncidentSummary,
  });

  const { data: list, isLoading } = useQuery({
    queryKey: ["incidents"],
    queryFn: () => operationsService.listIncidents({ limit: 50 }),
  });

  const createMut = useMutation({
    mutationFn: operationsService.createIncident,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["incident-summary"] });
      setShowForm(false);
      setNewInc({ incident_type: INCIDENT_TYPES[0], severity: "HIGH", title: "", root_cause: "", impact: "" });
    },
  });

  const resolveMut = useMutation({
    mutationFn: ({ id, res }: { id: number; res: string }) =>
      operationsService.resolveIncident(id, { resolution: res }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["incidents"] });
      qc.invalidateQueries({ queryKey: ["incident-summary"] });
      setResolveId(null);
      setResolution("");
    },
  });

  return (
    <div className="space-y-4">
      {/* Summary */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Card title="Total">
            <p className="text-2xl font-bold">{summary.total}</p>
          </Card>
          <Card title="Open">
            <p className={cn("text-2xl font-bold", summary.open > 0 ? "text-loss" : "text-profit")}>
              {summary.open}
            </p>
          </Card>
          <Card title="Avg Duration">
            <p className="text-2xl font-bold">{summary.avg_duration_min}m</p>
          </Card>
          <Card title="By Severity">
            <div className="space-y-1">
              {Object.entries(summary.by_severity).map(([sev, counts]) => (
                <div key={sev} className="flex items-center justify-between text-xs">
                  <SeverityBadge severity={sev} />
                  <span>{counts.open} open / {counts.total} total</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => setShowForm((s) => !s)}
          className="rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
        >
          + Log Incident
        </button>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="rounded-lg border bg-card p-4 space-y-3">
          <h3 className="text-sm font-semibold">Log New Incident</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">Type</label>
              <select
                value={newInc.incident_type}
                onChange={(e) => setNewInc((p) => ({ ...p, incident_type: e.target.value }))}
                className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs"
              >
                {INCIDENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">Severity</label>
              <select
                value={newInc.severity}
                onChange={(e) => setNewInc((p) => ({ ...p, severity: e.target.value }))}
                className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs"
              >
                {["LOW","MEDIUM","HIGH","CRITICAL"].map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Title *</label>
            <input
              value={newInc.title}
              onChange={(e) => setNewInc((p) => ({ ...p, title: e.target.value }))}
              placeholder="Brief description"
              className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Root Cause</label>
            <input
              value={newInc.root_cause}
              onChange={(e) => setNewInc((p) => ({ ...p, root_cause: e.target.value }))}
              placeholder="Optional"
              className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Impact</label>
            <input
              value={newInc.impact}
              onChange={(e) => setNewInc((p) => ({ ...p, impact: e.target.value }))}
              placeholder="Optional"
              className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs"
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => createMut.mutate(newInc)}
              disabled={!newInc.title || createMut.isPending}
              className="rounded bg-loss px-3 py-1.5 text-xs font-medium text-white hover:bg-loss/90 disabled:opacity-50"
            >
              {createMut.isPending ? "Logging…" : "Log Incident"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="rounded border px-3 py-1.5 text-xs hover:bg-muted/30"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Resolve dialog */}
      {resolveId !== null && (
        <div className="rounded-lg border bg-card p-4 space-y-3">
          <h3 className="text-sm font-semibold">Resolve Incident #{resolveId}</h3>
          <div>
            <label className="text-xs text-muted-foreground">Resolution *</label>
            <textarea
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
              placeholder="Describe how the incident was resolved"
              rows={3}
              className="mt-1 w-full rounded border bg-background px-2 py-1 text-xs"
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => resolveMut.mutate({ id: resolveId, res: resolution })}
              disabled={!resolution || resolveMut.isPending}
              className="rounded bg-profit px-3 py-1.5 text-xs font-medium text-white hover:bg-profit/90 disabled:opacity-50"
            >
              {resolveMut.isPending ? "Resolving…" : "Mark Resolved"}
            </button>
            <button
              onClick={() => { setResolveId(null); setResolution(""); }}
              className="rounded border px-3 py-1.5 text-xs hover:bg-muted/30"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Incident list */}
      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !list?.incidents.length ? (
        <p className="text-sm text-muted-foreground">No incidents recorded.</p>
      ) : (
        <div className="space-y-2">
          {list.incidents.map((inc) => (
            <IncidentRow key={inc.id} inc={inc} onResolve={() => setResolveId(inc.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

function IncidentRow({ inc, onResolve }: { inc: Incident; onResolve: () => void }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div
      className={cn(
        "rounded-lg border p-3 transition-all",
        inc.is_resolved ? "border-border bg-muted/10 opacity-70" : "border-border bg-card",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <SeverityBadge severity={inc.severity} />
          <span className="truncate text-sm font-medium">{inc.title}</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-muted-foreground">
            {inc.incident_type.replace(/_/g, " ")}
          </span>
          {inc.is_resolved ? (
            <span className="text-xs text-profit">Resolved</span>
          ) : (
            <button
              onClick={onResolve}
              className="rounded border border-profit/40 px-2 py-0.5 text-xs text-profit hover:bg-profit/10"
            >
              Resolve
            </button>
          )}
          <button
            onClick={() => setExpanded((e) => !e)}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {expanded ? "▲" : "▼"}
          </button>
        </div>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        {new Date(inc.start_time).toLocaleString()}
        {inc.duration_minutes !== null && ` · ${inc.duration_minutes}min`}
      </div>
      {expanded && (
        <div className="mt-2 space-y-1 text-xs text-muted-foreground">
          {inc.root_cause  && <div><span className="font-medium">Root cause: </span>{inc.root_cause}</div>}
          {inc.impact      && <div><span className="font-medium">Impact: </span>{inc.impact}</div>}
          {inc.resolution  && <div><span className="font-medium">Resolution: </span>{inc.resolution}</div>}
          {inc.recovery_actions && <div><span className="font-medium">Recovery: </span>{inc.recovery_actions}</div>}
        </div>
      )}
    </div>
  );
}

// ─── Tab: Scan Metrics ────────────────────────────────────────────────────────

function ScanMetricsTab() {
  const { data: summary } = useQuery({
    queryKey: ["scan-metrics-summary"],
    queryFn: () => operationsService.getScanMetricsSummary(24),
    refetchInterval: 60_000,
  });
  const { data: recent, isLoading } = useQuery({
    queryKey: ["scan-metrics"],
    queryFn: () => operationsService.getScanMetrics(30),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4">
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
          <Card title="Cycles (24h)">
            <p className="text-2xl font-bold">{summary.cycles}</p>
          </Card>
          <Card title="Avg Duration">
            <p className="text-2xl font-bold">
              {summary.avg_duration_sec !== null ? `${summary.avg_duration_sec}s` : "—"}
            </p>
          </Card>
          <Card title="Signals Gen">
            <p className="text-2xl font-bold">{summary.total_signals}</p>
          </Card>
          <Card title="Avg Score">
            <p className="text-2xl font-bold">
              {summary.avg_score !== null ? summary.avg_score.toFixed(1) : "—"}
            </p>
          </Card>
          <Card title="Avg Confidence">
            <p className="text-2xl font-bold">
              {summary.avg_confidence !== null ? summary.avg_confidence.toFixed(1) : "—"}
            </p>
          </Card>
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : !recent?.length ? (
        <p className="text-sm text-muted-foreground">No scan metrics recorded yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr>
                {["Time","Duration","Symbols","Signals","Rejected","Avg Score","VIX","Mode"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium text-muted-foreground">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {recent.map((m) => (
                <tr key={m.id} className="border-t hover:bg-muted/10">
                  <td className="px-3 py-2">{new Date(m.cycle_at).toLocaleTimeString()}</td>
                  <td className="px-3 py-2">{m.scan_duration_seconds?.toFixed(1) ?? "—"}s</td>
                  <td className="px-3 py-2">{m.symbols_scanned ?? "—"}</td>
                  <td className="px-3 py-2">{m.signals_generated ?? "—"}</td>
                  <td className="px-3 py-2">{m.signals_rejected ?? "—"}</td>
                  <td className="px-3 py-2">{m.avg_score?.toFixed(1) ?? "—"}</td>
                  <td className="px-3 py-2">{m.india_vix?.toFixed(1) ?? "—"}</td>
                  <td className="px-3 py-2 text-muted-foreground">{m.execution_mode ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Tab: Pre-Market ──────────────────────────────────────────────────────────

function PreMarketTab() {
  const qc = useQueryClient();
  const { data: latest } = useQuery({
    queryKey: ["pre-market-latest"],
    queryFn: operationsService.getPreMarketLatest,
  });
  const { data: history } = useQuery({
    queryKey: ["pre-market-history"],
    queryFn: () => operationsService.getPreMarketHistory(14),
  });

  const runMut = useMutation({
    mutationFn: operationsService.runPreMarketCheck,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pre-market-latest"] });
      qc.invalidateQueries({ queryKey: ["pre-market-history"] });
    },
  });

  const CHECKS = [
    ["db_connected",        "Database"],
    ["redis_connected",     "Redis"],
    ["kite_authenticated",  "Kite Auth"],
    ["websocket_connected", "WebSocket"],
    ["scanner_healthy",     "Scanner"],
    ["option_chain_healthy","Option Chain"],
    ["candles_available",   "Candles"],
  ] as const;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button
          onClick={() => runMut.mutate()}
          disabled={runMut.isPending}
          className="rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {runMut.isPending ? "Running…" : "Run Checklist Now"}
        </button>
        {runMut.isSuccess && (
          <span className="text-xs text-profit">Completed successfully</span>
        )}
      </div>

      {latest && (
        <Card title={`Latest Check — ${latest.check_date}`}>
          <div className="mb-3 flex items-center gap-3">
            <StatusBadge status={latest.overall_status} />
            <span className="text-xs text-muted-foreground">
              {new Date(latest.check_time).toLocaleString()}
            </span>
            {latest.execution_lock_mode && (
              <span className="text-xs text-muted-foreground">
                Lock: <span className="font-medium">{latest.execution_lock_mode}</span>
              </span>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {CHECKS.map(([key, label]) => (
              <div key={key} className="flex items-center gap-2 text-xs">
                <BoolDot ok={latest[key] as boolean} />
                <span className={latest[key] ? "" : "text-loss"}>{label}</span>
              </div>
            ))}
          </div>
          {latest.failed_checks.length > 0 && (
            <div className="mt-3 rounded bg-loss/10 p-2 text-xs text-loss">
              Failed: {latest.failed_checks.join(", ")}
            </div>
          )}
          {latest.notes && (
            <p className="mt-2 text-xs text-muted-foreground">{latest.notes}</p>
          )}
        </Card>
      )}

      {history && history.length > 0 && (
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr>
                {["Date","Time","Status","Kite","Lock Mode","Failed"].map((h) => (
                  <th key={h} className="px-3 py-2 text-left font-medium text-muted-foreground">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((h, i) => (
                <tr key={i} className="border-t hover:bg-muted/10">
                  <td className="px-3 py-2">{h.check_date}</td>
                  <td className="px-3 py-2">{new Date(h.check_time).toLocaleTimeString()}</td>
                  <td className="px-3 py-2"><StatusBadge status={h.overall_status} /></td>
                  <td className="px-3 py-2"><BoolDot ok={h.kite_authenticated} /></td>
                  <td className="px-3 py-2 text-muted-foreground">{h.execution_lock_mode ?? "—"}</td>
                  <td className="px-3 py-2 text-loss">
                    {h.failed_checks.length > 0 ? h.failed_checks.join(", ") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Tab: Architecture Freeze ─────────────────────────────────────────────────

function FreezeTab() {
  const { data } = useQuery({
    queryKey: ["platform-readiness"],
    queryFn: operationsService.getReadiness,
  });
  const freeze = data?.components?.architecture_freeze;

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-lg font-bold text-primary">Architecture FROZEN</span>
          <StatusBadge status="READY" />
        </div>
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-muted-foreground">Frozen since: </span>
            <span className="font-medium">{freeze?.freeze_date ?? "2026-06-27"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Phase: </span>
            <span className="font-medium">{freeze?.freeze_phase ?? "Phase 24"}</span>
          </div>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">{freeze?.detail}</p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card title="Frozen Modules (No Changes)">
          <ul className="space-y-1 text-xs text-muted-foreground">
            {((freeze?.frozen_modules as string[]) ?? []).map((m) => (
              <li key={m} className="flex items-center gap-2">
                <span className="text-loss">✕</span>
                {m}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Allowed Changes">
          <ul className="space-y-1 text-xs text-muted-foreground">
            {((freeze?.allowed as string[]) ?? []).map((a) => (
              <li key={a} className="flex items-center gap-2">
                <span className="text-profit">✓</span>
                {a.replace(/_/g, " ")}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="rounded-lg border bg-muted/10 p-4">
        <h3 className="mb-2 text-sm font-semibold">Deployment Stage Progression</h3>
        <div className="flex items-center gap-2 flex-wrap text-xs">
          {["DEV", "PAPER", "ONE_LOT", "TWO_LOTS", "SCALED"].map((stage, i, arr) => (
            <div key={stage} className="flex items-center gap-2">
              <span className="rounded border px-2 py-0.5 font-medium">{stage}</span>
              {i < arr.length - 1 && <span className="text-muted-foreground">→</span>}
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Stage progression is controlled by the Deployment Readiness engine. Each stage
          requires passing score thresholds: NOT_READY / LIMITED / READY_FOR_SMALL_CAPITAL / READY_FOR_SCALING.
          500+ completed trades required before architecture can be unfrozen.
        </p>
      </div>
    </div>
  );
}

// ─── Main View ────────────────────────────────────────────────────────────────

const TABS = [
  { id: "readiness",  label: "Platform Readiness" },
  { id: "incidents",  label: "Incidents" },
  { id: "scan",       label: "Scan Metrics" },
  { id: "premarket",  label: "Pre-Market" },
  { id: "freeze",     label: "Architecture Freeze" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function OperationsView() {
  const [tab, setTab] = useState<TabId>("readiness");

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">Operations</h1>
          <p className="text-sm text-muted-foreground">
            Platform health, incidents, scan metrics, and architecture freeze status.
          </p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px",
              tab === t.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {tab === "readiness"  && <ReadinessTab />}
        {tab === "incidents"  && <IncidentsTab />}
        {tab === "scan"       && <ScanMetricsTab />}
        {tab === "premarket"  && <PreMarketTab />}
        {tab === "freeze"     && <FreezeTab />}
      </div>
    </div>
  );
}
