"use client";

import { useEffect, useState } from "react";
import { strategyVersioningService } from "@/services/research.service";

interface Version {
  id: string;
  name: string;
  is_immutable: boolean;
  created_at: string;
}

export function ResearchHubView() {
  const [versions, setVersions] = useState<Version[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    strategyVersioningService
      .list()
      .then((d) => setVersions(d.versions ?? []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Research Hub</h1>
      <p className="text-muted-foreground text-sm">
        Offline strategy research platform — re-weights historical signal scores without touching production.
      </p>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Strategy Versions", href: "/strategy-versions", desc: "Version registry & V1 baseline" },
          { label: "Parameter Optimization", href: "/parameter-optimization", desc: "Grid search over weight combinations" },
          { label: "Walk-Forward Analysis", href: "/walk-forward", desc: "Rolling OOS validation windows" },
          { label: "Monte Carlo", href: "/monte-carlo", desc: "Bootstrap P&L distribution" },
          { label: "Regime Performance", href: "/regime-performance", desc: "Win rate by regime & direction" },
          { label: "Symbol Rankings", href: "/symbol-rankings", desc: "Composite ticker leaderboard" },
          { label: "False Positive Analysis", href: "/false-positive", desc: "FP/FN rates by component bucket" },
          { label: "Strategy Promotion", href: "/strategy-promotion", desc: "Promotion queue & gating criteria" },
        ].map((card) => (
          <a
            key={card.href}
            href={card.href}
            className="block rounded-lg border p-4 hover:bg-muted transition-colors"
          >
            <div className="font-medium">{card.label}</div>
            <div className="text-sm text-muted-foreground mt-1">{card.desc}</div>
          </a>
        ))}
      </div>

      <div className="rounded-lg border">
        <div className="px-4 py-3 border-b font-medium">Strategy Versions</div>
        {loading ? (
          <div className="p-4 text-sm text-muted-foreground">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Immutable</th>
                <th className="px-4 py-2">Created</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id} className="border-b last:border-0">
                  <td className="px-4 py-2">{v.name}</td>
                  <td className="px-4 py-2">
                    {v.is_immutable ? (
                      <span className="text-xs bg-yellow-100 text-yellow-800 rounded px-1.5 py-0.5">Locked</span>
                    ) : (
                      <span className="text-xs bg-green-100 text-green-800 rounded px-1.5 py-0.5">Mutable</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">
                    {v.created_at ? new Date(v.created_at).toLocaleDateString() : "—"}
                  </td>
                </tr>
              ))}
              {versions.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-4 py-4 text-center text-muted-foreground">
                    No versions yet
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
