"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  experimentService,
  type Experiment,
  type ExperimentValidation,
  type GovernanceReport,
  type PlatformStatus,
} from "@/services/experiment.service";

// ─── Constants ────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  DRAFT:     "bg-slate-700/50 text-slate-400 border-slate-600/40",
  ACTIVE:    "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  PAUSED:    "bg-amber-500/15 text-amber-400 border-amber-500/30",
  COMPLETED: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  REJECTED:  "bg-red-500/15 text-red-400 border-red-500/30",
};

const APPROVAL_COLORS: Record<string, string> = {
  PENDING:  "text-amber-400",
  APPROVED: "text-emerald-400",
  REJECTED: "text-red-400",
};

const RECOMMENDATION_COLORS: Record<string, string> = {
  DEPLOY:            "text-emerald-400",
  CONTINUE:          "text-blue-400",
  REJECT:            "text-red-400",
  INSUFFICIENT_DATA: "text-slate-400",
};

const RISK_COLORS: Record<string, string> = {
  LOW:    "text-emerald-400",
  MEDIUM: "text-amber-400",
  HIGH:   "text-red-400",
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex rounded border px-1.5 py-0.5 text-[11px] font-semibold ${STATUS_COLORS[status] ?? "text-slate-400 border-slate-600"}`}>
      {status}
    </span>
  );
}

function PlatformStatusCard({ data }: { data: PlatformStatus }) {
  return (
    <div className={`rounded-xl border p-5 ${data.is_frozen ? "border-amber-500/30 bg-amber-500/5" : "border-slate-700/60 bg-slate-800/40"}`}>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-slate-200">Platform Status</h2>
        <span className={`rounded border px-2 py-0.5 text-xs font-bold ${data.is_frozen ? "bg-amber-500/15 text-amber-400 border-amber-500/30" : "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"}`}>
          {data.architecture_status}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 mb-3">
        {Object.entries(data.version_manifest).map(([k, v]) => (
          <div key={k} className="rounded bg-slate-800/60 px-2 py-1.5">
            <p className="text-[10px] text-slate-500 uppercase">{k.replace("_version", "")}</p>
            <p className="text-xs font-mono text-slate-300">{v}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500 leading-relaxed">{data.evolution_policy}</p>
    </div>
  );
}

function ExperimentCard({
  exp, onSelect,
}: {
  exp: Experiment;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(exp.experiment_id)}
      className="w-full text-left rounded-xl border border-slate-700/60 bg-slate-800/40 p-4 hover:border-slate-600 hover:bg-slate-800/60 transition-colors"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <span className="text-xs text-slate-500 font-mono">{exp.experiment_id}</span>
          <h3 className="text-sm font-semibold text-slate-100 mt-0.5">{exp.title}</h3>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <StatusBadge status={exp.status} />
          <span className={`text-[10px] font-medium ${APPROVAL_COLORS[exp.approval_status]}`}>
            {exp.approval_status}
          </span>
        </div>
      </div>
      <p className="text-xs text-slate-400 line-clamp-2 mb-3">{exp.hypothesis}</p>
      <div className="flex gap-4 text-[11px] text-slate-500">
        <span>KPI: <span className="text-slate-300">{exp.primary_kpi}</span></span>
        <span>Min: <span className="text-slate-300">{exp.minimum_sample_size}</span></span>
        <span>Treatment: <span className="text-slate-300">{exp.treatment_allocation_pct}%</span></span>
        <span>By: <span className="text-slate-300">{exp.author}</span></span>
      </div>
    </button>
  );
}

function ValidationPanel({ expId }: { expId: string }) {
  const q = useQuery({
    queryKey: ["exp-validation", expId],
    queryFn: () => experimentService.getValidation(expId),
    staleTime: 60_000,
  });

  if (q.isLoading) return <p className="text-sm text-slate-500 py-4">Loading validation…</p>;
  if (!q.data) return <p className="text-sm text-slate-500 py-4">No validation data yet</p>;

  const v = q.data.validation;
  const recColor = RECOMMENDATION_COLORS[v.recommendation] ?? "text-slate-300";

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span className={`text-lg font-bold ${recColor}`}>{v.recommendation.replace("_", " ")}</span>
        <span className={`text-xs font-medium ${RISK_COLORS[v.risk_assessment]}`}>
          Risk: {v.risk_assessment}
        </span>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed">{v.recommendation_reason}</p>

      <div className="grid grid-cols-2 gap-3">
        {[
          { label: "Control Win Rate",   value: `${v.control_win_rate}%`,   sub: `CI [${v.control_wilson.lower}%, ${v.control_wilson.upper}%]` },
          { label: "Treatment Win Rate", value: `${v.treatment_win_rate}%`, sub: `CI [${v.treatment_wilson.lower}%, ${v.treatment_wilson.upper}%]` },
          { label: "Improvement",        value: `${v.improvement_pct > 0 ? "+" : ""}${v.improvement_pct}%`, sub: `z = ${v.z_score}` },
          { label: "P-Value",            value: v.p_value.toFixed(4), sub: v.is_significant ? "✓ Significant" : "✗ Not significant" },
        ].map((c) => (
          <div key={c.label} className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-3">
            <p className="text-[10px] text-slate-500 uppercase">{c.label}</p>
            <p className="text-base font-semibold text-slate-100 mt-0.5">{c.value}</p>
            <p className={`text-[10px] mt-0.5 ${c.sub.includes("✓") ? "text-emerald-400" : c.sub.includes("✗") ? "text-red-400" : "text-slate-500"}`}>
              {c.sub}
            </p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3">
        {(["control", "treatment"] as const).map((grp) => {
          const d = q.data![grp] as Record<string, unknown>;
          return (
            <div key={grp} className="rounded-lg border border-slate-700/60 bg-slate-800/40 p-3">
              <p className="text-xs font-semibold text-slate-400 uppercase mb-2">{grp}</p>
              <div className="space-y-0.5 text-xs text-slate-400">
                <p>Trades: <span className="text-slate-200">{String(d.trades ?? "—")}</span></p>
                <p>Wins: <span className="text-slate-200">{String(d.wins ?? "—")}</span></p>
                <p>Avg MFE: <span className="text-slate-200">{d.avg_mfe != null ? `${d.avg_mfe}%` : "—"}</span></p>
                <p>PF: <span className="text-slate-200">{d.profit_factor != null ? String(d.profit_factor) : "—"}</span></p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function GovernancePanel({ expId }: { expId: string }) {
  const q = useQuery({
    queryKey: ["exp-governance", expId],
    queryFn: () => experimentService.getGovernance(expId),
    staleTime: 60_000,
  });

  if (q.isLoading) return <p className="text-sm text-slate-500 py-4">Checking governance gates…</p>;
  if (!q.data) return null;

  const r = q.data;
  return (
    <div className="space-y-3">
      <div className={`rounded-lg border px-4 py-3 ${r.approved ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-300" : "border-red-500/30 bg-red-500/5 text-red-300"}`}>
        <p className="text-sm font-semibold">{r.overall} {r.approved ? "✓" : "✗"}</p>
        <p className="text-xs mt-0.5 opacity-80">{r.summary}</p>
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-slate-700/60 text-slate-400 text-[10px] uppercase">
            <th className="pb-1.5 text-left">Gate</th>
            <th className="pb-1.5 text-center">Status</th>
            <th className="pb-1.5 text-left">Detail</th>
          </tr>
        </thead>
        <tbody>
          {r.gates.map((g) => (
            <tr key={g.gate} className="border-b border-slate-700/30 last:border-0">
              <td className="py-1.5 text-slate-300 font-mono text-[11px]">{g.gate.replace(/_/g, " ")}</td>
              <td className="py-1.5 text-center">
                <span className={g.passed ? "text-emerald-400" : "text-red-400"}>{g.passed ? "✓" : "✗"}</span>
              </td>
              <td className="py-1.5 text-slate-400 leading-snug">{g.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExperimentDetail({ expId, onBack }: { expId: string; onBack: () => void }) {
  const [tab, setTab] = useState<"overview" | "validation" | "governance">("overview");
  const qc = useQueryClient();
  const { data: exp } = useQuery({
    queryKey: ["experiment", expId],
    queryFn: () => experimentService.getExperiment(expId),
    staleTime: 30_000,
  });

  const approveMut = useMutation({
    mutationFn: () => experimentService.approveExperiment(expId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["experiment", expId] }),
  });

  if (!exp) return <p className="text-slate-500 text-sm py-8 text-center">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="text-slate-400 hover:text-slate-200 text-sm">← Back</button>
        <span className="text-xs font-mono text-slate-500">{exp.experiment_id}</span>
        <StatusBadge status={exp.status} />
        <span className={`text-xs font-medium ${APPROVAL_COLORS[exp.approval_status]}`}>{exp.approval_status}</span>
      </div>

      <div>
        <h1 className="text-xl font-semibold text-slate-100">{exp.title}</h1>
        {exp.description && <p className="text-sm text-slate-400 mt-1">{exp.description}</p>}
      </div>

      <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 px-4 py-3">
        <p className="text-[10px] text-slate-500 uppercase mb-1">Hypothesis</p>
        <p className="text-sm text-slate-300 leading-relaxed">{exp.hypothesis}</p>
      </div>

      {exp.approval_status === "PENDING" && (
        <button
          onClick={() => approveMut.mutate()}
          disabled={approveMut.isPending}
          className="rounded px-4 py-2 text-sm font-medium bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {approveMut.isPending ? "Approving…" : "Approve Experiment"}
        </button>
      )}

      <div className="border-b border-slate-700/60">
        <nav className="flex gap-4">
          {(["overview", "validation", "governance"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`border-b-2 pb-2 text-sm font-medium transition-colors ${tab === t ? "border-blue-500 text-blue-400" : "border-transparent text-slate-400 hover:text-slate-200"}`}>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </nav>
      </div>

      {tab === "overview" && (
        <div className="grid gap-3 sm:grid-cols-2">
          {[
            ["Primary KPI",   exp.primary_kpi],
            ["Min Sample",    exp.minimum_sample_size],
            ["Treatment %",   `${exp.treatment_allocation_pct}%`],
            ["Author",        exp.author],
            ["Baseline Ver",  exp.baseline_strategy_version ?? "—"],
            ["Candidate Ver", exp.candidate_strategy_version ?? "—"],
            ["Created",       new Date(exp.created_at).toLocaleDateString()],
            ["Approved By",   exp.approved_by ?? "—"],
          ].map(([l, v]) => (
            <div key={String(l)} className="flex justify-between text-sm border-b border-slate-700/30 pb-1.5">
              <span className="text-slate-500">{l}</span>
              <span className="text-slate-200 font-medium">{String(v)}</span>
            </div>
          ))}
          {exp.rollback_plan && (
            <div className="sm:col-span-2 rounded-lg border border-slate-700/60 bg-slate-800/40 p-3">
              <p className="text-[10px] text-slate-500 uppercase mb-1">Rollback Plan</p>
              <p className="text-xs text-slate-300">{exp.rollback_plan}</p>
            </div>
          )}
          {exp.conclusion && (
            <div className="sm:col-span-2 rounded-lg border border-blue-500/30 bg-blue-500/5 p-3">
              <p className="text-[10px] text-blue-400 uppercase mb-1">Conclusion</p>
              <p className="text-xs text-slate-300">{exp.conclusion}</p>
            </div>
          )}
        </div>
      )}

      {tab === "validation" && <ValidationPanel expId={expId} />}
      {tab === "governance" && <GovernancePanel expId={expId} />}
    </div>
  );
}

// ─── Main view ────────────────────────────────────────────────────────────────

export default function ExperimentsView() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [mainTab, setMainTab] = useState<"experiments" | "platform">("experiments");

  const experimentsQ = useQuery({
    queryKey: ["experiments", statusFilter],
    queryFn: () => experimentService.listExperiments(statusFilter),
    staleTime: 30_000,
  });

  const platformQ = useQuery({
    queryKey: ["platform-status"],
    queryFn: () => experimentService.getPlatformStatus(),
    staleTime: 60_000,
  });

  const weeklyQ = useQuery({
    queryKey: ["weekly-review"],
    queryFn: () => experimentService.getWeeklyReview(7),
    staleTime: 300_000,
    enabled: mainTab === "platform",
  });

  if (selectedId) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-6">
        <ExperimentDetail expId={selectedId} onBack={() => setSelectedId(null)} />
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100">Phase 25 — Experiment Framework</h1>
          <p className="text-sm text-slate-400 mt-0.5">Evidence-driven strategy evolution. No change ships without statistical proof.</p>
        </div>
        {platformQ.data && (
          <span className={`rounded border px-3 py-1 text-xs font-bold ${platformQ.data.is_frozen ? "border-amber-500/40 bg-amber-500/10 text-amber-400" : "border-slate-600 text-slate-400"}`}>
            {platformQ.data.architecture_status}
          </span>
        )}
      </div>

      <div className="border-b border-slate-700/60">
        <nav className="flex gap-6">
          {(["experiments", "platform"] as const).map((t) => (
            <button key={t} onClick={() => setMainTab(t)}
              className={`border-b-2 pb-2 text-sm font-medium transition-colors ${mainTab === t ? "border-blue-500 text-blue-400" : "border-transparent text-slate-400 hover:text-slate-200"}`}>
              {t === "experiments" ? "Experiments" : "Platform Status"}
            </button>
          ))}
        </nav>
      </div>

      {mainTab === "experiments" && (
        <div className="space-y-4">
          <div className="flex gap-2 flex-wrap">
            {[undefined, "DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "REJECTED"].map((s) => (
              <button key={String(s)} onClick={() => setStatusFilter(s)}
                className={`rounded px-3 py-1 text-xs transition-colors ${statusFilter === s ? "bg-blue-600 text-white" : "bg-slate-700 text-slate-400 hover:text-slate-200"}`}>
                {s ?? "All"}
              </button>
            ))}
          </div>

          {experimentsQ.isLoading ? (
            <p className="text-slate-500 text-sm py-8 text-center">Loading experiments…</p>
          ) : !experimentsQ.data?.experiments?.length ? (
            <div className="rounded-xl border border-slate-700/60 bg-slate-800/30 p-12 text-center">
              <p className="text-slate-400 text-sm">No experiments yet.</p>
              <p className="text-slate-500 text-xs mt-2">
                Create your first A/B experiment via the API: POST /api/v1/experiments
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {experimentsQ.data.experiments.map((exp) => (
                <ExperimentCard key={exp.experiment_id} exp={exp} onSelect={setSelectedId} />
              ))}
            </div>
          )}
        </div>
      )}

      {mainTab === "platform" && (
        <div className="space-y-5">
          {platformQ.data && <PlatformStatusCard data={platformQ.data} />}

          {weeklyQ.isLoading && <p className="text-slate-500 text-sm">Generating weekly review…</p>}
          {weeklyQ.data && (() => {
            const d = weeklyQ.data;
            const perf = d.section_3_performance as Record<string, unknown> | undefined;
            const cal  = d.section_4_calibration  as Record<string, unknown> | undefined;
            const recs = d.recommendation_summary as string[] | undefined;
            return (
              <div className="space-y-4">
                <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
                  Weekly Research Review — {String(d.week_ending)}
                </h2>

                {perf && (
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    {[
                      { l: "Win Rate",      v: perf.win_rate      != null ? `${perf.win_rate}%`       : "—" },
                      { l: "Avg MFE",       v: perf.avg_mfe       != null ? `${perf.avg_mfe}%`        : "—" },
                      { l: "Profit Factor", v: perf.profit_factor != null ? String(perf.profit_factor) : "—" },
                      { l: "Avg Score",     v: perf.avg_score     != null ? String(perf.avg_score)    : "—" },
                    ].map((c) => (
                      <div key={c.l} className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-3">
                        <p className="text-[10px] text-slate-500 uppercase">{c.l}</p>
                        <p className="text-base font-semibold text-slate-100 mt-0.5">{c.v}</p>
                      </div>
                    ))}
                  </div>
                )}

                {cal && (
                  <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4">
                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Target Calibration</h3>
                    <div className="flex flex-wrap gap-4 text-xs">
                      <span className="text-slate-400">Status: <span className={`font-semibold ${cal.calibration_status === "WELL_CALIBRATED" ? "text-emerald-400" : cal.calibration_status === "SLIGHTLY_AGGRESSIVE" ? "text-amber-400" : "text-red-400"}`}>{String(cal.calibration_status)}</span></span>
                      <span className="text-slate-400">Avg Realism: <span className="text-slate-200">{cal.avg_target_realism != null ? `${cal.avg_target_realism}%` : "—"}</span></span>
                      <span className="text-slate-400">Unrealistic Rate: <span className="text-slate-200">{cal.unrealistic_rate != null ? `${cal.unrealistic_rate}%` : "—"}</span></span>
                    </div>
                  </div>
                )}

                {recs && recs.length > 0 && (
                  <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4">
                    <h3 className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-3">Recommendations</h3>
                    <ul className="space-y-2">
                      {recs.map((r, i) => (
                        <li key={i} className="flex gap-2 text-sm text-slate-300">
                          <span className="text-blue-400 shrink-0">→</span>
                          {r}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
