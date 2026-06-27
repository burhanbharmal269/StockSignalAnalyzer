import apiClient from "@/lib/api-client";

const BASE = "/api/v1/platform";

export interface ComponentStatus {
  status: "READY" | "WARNING" | "NOT_READY";
  [key: string]: unknown;
}

export interface PlatformReadiness {
  overall: "READY" | "WARNING" | "NOT_READY";
  recommendation: string;
  components: {
    database: ComponentStatus;
    redis: ComponentStatus;
    kite: ComponentStatus;
    market_data: ComponentStatus;
    websocket: ComponentStatus;
    scanner: ComponentStatus;
    background_tasks: ComponentStatus;
    option_chain: ComponentStatus;
    data_quality: ComponentStatus;
    execution_quality: ComponentStatus;
    deployment_stage: ComponentStatus;
    architecture_freeze: ComponentStatus;
  };
  checked_at: string;
}

export interface Incident {
  id: number;
  incident_type: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  title: string;
  start_time: string;
  end_time: string | null;
  duration_minutes: number | null;
  root_cause: string | null;
  resolution: string | null;
  impact: string | null;
  recovery_actions: string | null;
  is_resolved: boolean;
  created_at: string;
  updated_at: string;
}

export interface IncidentListResponse {
  total: number;
  limit: number;
  offset: number;
  incidents: Incident[];
}

export interface IncidentSummary {
  total: number;
  open: number;
  avg_duration_min: number;
  by_severity: Record<string, { total: number; open: number }>;
  by_type: Record<string, number>;
}

export interface ScanCycleMetric {
  id: number;
  cycle_at: string;
  scan_duration_seconds: number | null;
  symbols_scanned: number | null;
  symbols_failed: number | null;
  signals_generated: number | null;
  signals_rejected: number | null;
  signals_gated: number | null;
  avg_score: number | null;
  avg_confidence: number | null;
  avg_data_quality: number | null;
  india_vix: number | null;
  market_context: string | null;
  execution_mode: string | null;
  gate_failures: Record<string, number> | null;
}

export interface ScanMetricsSummary {
  hours: number;
  cycles: number;
  avg_duration_sec: number | null;
  avg_symbols: number | null;
  total_signals: number;
  total_rejected: number;
  avg_score: number | null;
  avg_confidence: number | null;
  avg_data_quality: number | null;
  last_cycle_at: string | null;
}

export interface PreMarketCheck {
  check_date: string;
  check_time: string;
  db_connected: boolean;
  redis_connected: boolean;
  kite_authenticated: boolean;
  websocket_connected: boolean;
  scanner_healthy: boolean;
  option_chain_healthy: boolean;
  candles_available: boolean;
  execution_lock_mode: string | null;
  overall_status: "READY" | "WARNING" | "NOT_READY" | "UNKNOWN";
  failed_checks: string[];
  notes: string | null;
}

export const operationsService = {
  // Readiness
  getReadiness: (): Promise<PlatformReadiness> =>
    apiClient.get(`${BASE}/readiness`).then((r) => r.data),

  runPreMarketCheck: (): Promise<Record<string, unknown>> =>
    apiClient.get(`${BASE}/readiness/run`).then((r) => r.data),

  // Incidents
  getIncidentSummary: (): Promise<IncidentSummary> =>
    apiClient.get(`${BASE}/incidents/summary`).then((r) => r.data),

  listIncidents: (params?: {
    limit?: number;
    offset?: number;
    incident_type?: string;
    severity?: string;
    unresolved_only?: boolean;
  }): Promise<IncidentListResponse> =>
    apiClient.get(`${BASE}/incidents`, { params }).then((r) => r.data),

  createIncident: (body: {
    incident_type: string;
    severity: string;
    title: string;
    root_cause?: string;
    impact?: string;
    recovery_actions?: string;
  }): Promise<Incident> =>
    apiClient.post(`${BASE}/incidents`, body).then((r) => r.data),

  resolveIncident: (
    id: number,
    body: { resolution: string; root_cause?: string; recovery_actions?: string },
  ): Promise<Incident> =>
    apiClient.post(`${BASE}/incidents/${id}/resolve`, body).then((r) => r.data),

  // Scan Metrics
  getScanMetrics: (limit?: number): Promise<ScanCycleMetric[]> =>
    apiClient.get(`${BASE}/scan-metrics`, { params: { limit } }).then((r) => r.data),

  getScanMetricsSummary: (hours?: number): Promise<ScanMetricsSummary> =>
    apiClient
      .get(`${BASE}/scan-metrics/summary`, { params: { hours } })
      .then((r) => r.data),

  // Pre-Market
  getPreMarketLatest: (): Promise<PreMarketCheck | null> =>
    apiClient.get(`${BASE}/pre-market`).then((r) => r.data),

  getPreMarketHistory: (limit?: number): Promise<PreMarketCheck[]> =>
    apiClient.get(`${BASE}/pre-market/history`, { params: { limit } }).then((r) => r.data),
};
