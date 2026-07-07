"use client";

import { useEffect, useState } from "react";
import { strategyVersioningService } from "@/services/research.service";

interface Version {
  id: string;
  name: string;
  description?: string;
  is_immutable: boolean;
  weights_snapshot: Record<string, number>;
  created_at: string;
}

export function StrategyVersionsView() {
  const [versions, setVersions] = useState<Version[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [baseId, setBaseId] = useState("");

  const load = () => {
    setLoading(true);
    strategyVersioningService
      .list()
      .then((d) => setVersions(d.versions ?? []))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async () => {
    if (!newName || !baseId) return;
    setCreating(true);
    try {
      const base = versions.find((v) => v.id === baseId);
      await strategyVersioningService.create({
        name: newName,
        base_version_id: baseId,
        weights: base?.weights_snapshot ?? {},
      });
      setNewName("");
      load();
    } catch (e) {
      console.error(e);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Strategy Versions</h1>

      <div className="rounded-lg border p-4 space-y-3">
        <div className="font-medium text-sm">Create Research Variant</div>
        <div className="flex gap-2">
          <input
            className="border rounded px-2 py-1 text-sm flex-1"
            placeholder="Version name (e.g. V2-HighOI)"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <select
            className="border rounded px-2 py-1 text-sm"
            value={baseId}
            onChange={(e) => setBaseId(e.target.value)}
          >
            <option value="">Base version…</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>{v.name}</option>
            ))}
          </select>
          <button
            className="bg-primary text-primary-foreground px-3 py-1 rounded text-sm disabled:opacity-50"
            onClick={handleCreate}
            disabled={creating || !newName || !baseId}
          >
            {creating ? "Creating…" : "Create"}
          </button>
        </div>
      </div>

      <div className="rounded-lg border">
        <div className="px-4 py-3 border-b font-medium">All Versions</div>
        {loading ? (
          <div className="p-4 text-sm text-muted-foreground">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left bg-muted/40">
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">OI</th>
                <th className="px-4 py-2">Trend</th>
                <th className="px-4 py-2">OC</th>
                <th className="px-4 py-2">Vol</th>
                <th className="px-4 py-2">VWAP</th>
                <th className="px-4 py-2">Sent</th>
                <th className="px-4 py-2">IV</th>
                <th className="px-4 py-2">Created</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id} className="border-b last:border-0 hover:bg-muted/20">
                  <td className="px-4 py-2 font-medium">{v.name}</td>
                  <td className="px-4 py-2">
                    {v.is_immutable ? (
                      <span className="text-xs bg-yellow-100 text-yellow-800 rounded px-1.5 py-0.5">V1 Locked</span>
                    ) : (
                      <span className="text-xs bg-blue-100 text-blue-800 rounded px-1.5 py-0.5">Research</span>
                    )}
                  </td>
                  {["oi_buildup","trend","option_chain","volume","vwap","sentiment","iv_analysis"].map((k) => (
                    <td key={k} className="px-4 py-2 text-right tabular-nums">
                      {v.weights_snapshot?.[k] ?? "—"}
                    </td>
                  ))}
                  <td className="px-4 py-2 text-muted-foreground">
                    {v.created_at ? new Date(v.created_at).toLocaleDateString() : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
