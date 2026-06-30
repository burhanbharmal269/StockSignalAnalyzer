import apiClient from "@/lib/api-client";

export interface Experiment {
  id: number;
  experiment_id: string;
  title: string;
  description: string | null;
  hypothesis: string;
  author: string;
  status: "DRAFT" | "ACTIVE" | "PAUSED" | "COMPLETED" | "REJECTED";
  approval_status: "PENDING" | "APPROVED" | "REJECTED";
  approved_by: string | null;
  approved_at: string | null;
  baseline_strategy_version: string | null;
  candidate_strategy_version: string | null;
  minimum_sample_size: number;
  preferred_sample_size: number;
  primary_kpi: string;
  secondary_kpi: string | null;
  expected_improvement_pct: number | null;
  treatment_allocation_pct: number;
  rollback_plan: string | null;
  failure_criteria: string | null;
  success_threshold: number | null;
  max_drawdown_allowed: number | null;
  notes: string | null;
  conclusion: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ValidationResult {
  control_win_rate: number;
  treatment_win_rate: number;
  control_wilson: { lower: number; upper: number; center: number };
  treatment_wilson: { lower: number; upper: number; center: number };
  improvement_pct: number;
  z_score: number;
  p_value: number;
  is_significant: boolean;
  confidence_level: number;
  recommendation: "DEPLOY" | "CONTINUE" | "REJECT" | "INSUFFICIENT_DATA";
  recommendation_reason: string;
  risk_assessment: "LOW" | "MEDIUM" | "HIGH";
}

export interface ExperimentValidation {
  experiment_id: string;
  experiment_title: string;
  status: string;
  minimum_sample_size: number;
  control: Record<string, unknown>;
  treatment: Record<string, unknown>;
  validation: ValidationResult;
}

export interface GovernanceGate {
  gate: string;
  passed: boolean;
  detail: string;
}

export interface GovernanceReport {
  experiment_id: string;
  overall: "APPROVED" | "BLOCKED";
  approved: boolean;
  blocking_gates: string[];
  summary: string;
  gates: GovernanceGate[];
}

export interface PlatformStatus {
  architecture_status: string;
  is_frozen: boolean;
  version_manifest: Record<string, string>;
  governance_thresholds: Record<string, unknown>;
  frozen_change_categories: string[];
  evolution_policy: string;
}

export const experimentService = {
  listExperiments: (status?: string) =>
    apiClient
      .get<{ count: number; experiments: Experiment[] }>("/experiments", { params: status ? { status } : {} })
      .then((r) => r.data),

  getExperiment: (id: string) =>
    apiClient.get<Experiment>(`/experiments/${id}`).then((r) => r.data),

  createExperiment: (payload: Partial<Experiment> & { experiment_id: string; title: string; hypothesis: string; author: string }) =>
    apiClient.post<Experiment>("/experiments", payload).then((r) => r.data),

  updateStatus: (id: string, status: string, notes?: string) =>
    apiClient.patch<Experiment>(`/experiments/${id}/status`, { status, notes }).then((r) => r.data),

  approveExperiment: (id: string) =>
    apiClient.post<Experiment>(`/experiments/${id}/approve`).then((r) => r.data),

  setConclusion: (id: string, conclusion: string) =>
    apiClient.put(`/experiments/${id}/conclusion`, { conclusion }).then((r) => r.data),

  getValidation: (id: string) =>
    apiClient.get<ExperimentValidation>(`/experiments/${id}/validation`).then((r) => r.data),

  getGovernance: (id: string) =>
    apiClient.get<GovernanceReport>(`/experiments/${id}/governance`).then((r) => r.data),

  getPlatformStatus: () =>
    apiClient.get<PlatformStatus>("/platform/status").then((r) => r.data),

  getWeeklyReview: (days = 7) =>
    apiClient.get<Record<string, unknown>>("/platform/weekly-review", { params: { days } }).then((r) => r.data),

  getPlatformEvents: (limit = 50) =>
    apiClient.get<{ count: number; events: unknown[] }>("/platform/events", { params: { limit } }).then((r) => r.data),
};
