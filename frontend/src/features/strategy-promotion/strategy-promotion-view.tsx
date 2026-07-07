"use client";

import { useEffect, useState } from "react";
import { promotionService, strategyVersioningService } from "@/services/research.service";

interface PromotionRow {
  id: string;
  version_id: string;
  version_name?: string;
  requested_by?: string;
  status: string;
  stat_test_passed?: boolean;
  oos_sharpe?: number;
  oos_win_rate?: number;
  walk_forward_windows?: number;
  reviewed_by?: string;
  created_at?: string;
}

const STATUS_COLORS: Record<string, string> = {
  PENDING: "bg-yellow-100 text-yellow-800",
  APPROVED: "bg-green-100 text-green-800",
  REJECTED: "bg-red-100 text-red-800",
  FAILED_GATES: "bg-orange-100 text-orange-800",
};

export function StrategyPromotionView() {
  const [queue, setQueue] = useState<PromotionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [versions, setVersions] = useState<{ id: string; name: string }[]>([]);
  const [versionId, setVersionId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [reviewer, setReviewer] = useState("");

  const load = () => {
    setLoading(true);
    promotionService
      .queue()
      .then((d) => setQueue(d.queue ?? []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    strategyVersioningService.list().then((d) => setVersions(d.versions ?? []));
  }, []);

  const requestPromotion = async () => {
    if (!versionId) return;
    setSubmitting(true);
    try {
      await promotionService.request(versionId, reviewer || undefined);
      setVersionId("");
      load();
    } catch (e) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  };

  const approve = async (id: string) => {
    await promotionService.approve(id, reviewer || undefined);
    load();
  };

  const reject = async (id: string) => {
    const reason = prompt("Rejection reason:");
    if (reason === null) return;
    await promotionService.reject(id, reviewer || undefined, reason);
    load();
  };

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Strategy Promotion Queue</h1>

      <div className="rounded-lg border p-4 space-y-3">
        <div className="font-medium text-sm">Request Promotion</div>
        <div className="flex gap-2 items-center flex-wrap">
          <select
            className="border rounded px-2 py-1 text-sm"
            value={versionId}
            onChange={(e) => setVersionId(e.target.value)}
          >
            <option value="">Select research version…</option>
            {versions.filter((v) => !v.name.includes("V1")).map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
          <input
            className="border rounded px-2 py-1 text-sm"
            placeholder="Reviewer name (optional)"
            value={reviewer}
            onChange={(e) => setReviewer(e.target.value)}
          />
          <button
            className="bg-primary text-primary-foreground px-3 py-1 rounded text-sm disabled:opacity-50"
            onClick={requestPromotion}
            disabled={submitting || !versionId}
          >
            {submitting ? "Submitting…" : "Request Promotion"}
          </button>
        </div>
        <div className="text-xs text-muted-foreground">
          Gates: OOS Sharpe &gt; 0.8 · ≥3 walk-forward windows · p &lt; 0.05 · manual approval
        </div>
      </div>

      <div className="rounded-lg border">
        <div className="px-4 py-3 border-b font-medium">Promotion Queue</div>
        {loading ? (
          <div className="p-4 text-sm text-muted-foreground">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left bg-muted/40">
                <th className="px-4 py-2">Version</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2 text-right">OOS Sharpe</th>
                <th className="px-4 py-2 text-right">WF Windows</th>
                <th className="px-4 py-2">Stat Test</th>
                <th className="px-4 py-2">Requested</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {queue.map((row) => (
                <tr key={row.id} className="border-b last:border-0 hover:bg-muted/20">
                  <td className="px-4 py-2 font-medium">{row.version_name ?? row.version_id.slice(0, 8)}</td>
                  <td className="px-4 py-2">
                    <span className={`text-xs rounded px-1.5 py-0.5 ${STATUS_COLORS[row.status] ?? "bg-muted"}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">
                    {row.oos_sharpe != null ? row.oos_sharpe.toFixed(3) : "—"}
                  </td>
                  <td className="px-4 py-2 text-right tabular-nums">{row.walk_forward_windows ?? "—"}</td>
                  <td className="px-4 py-2">
                    {row.stat_test_passed == null
                      ? "—"
                      : row.stat_test_passed
                      ? <span className="text-green-600">✓ Passed</span>
                      : <span className="text-red-600">✗ Failed</span>}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}
                  </td>
                  <td className="px-4 py-2">
                    {row.status === "PENDING" && (
                      <div className="flex gap-1">
                        <button
                          className="text-xs bg-green-600 text-white px-2 py-0.5 rounded hover:bg-green-700"
                          onClick={() => approve(row.id)}
                        >
                          Approve
                        </button>
                        <button
                          className="text-xs bg-red-600 text-white px-2 py-0.5 rounded hover:bg-red-700"
                          onClick={() => reject(row.id)}
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {queue.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-4 text-center text-muted-foreground">
                    No promotion requests
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
