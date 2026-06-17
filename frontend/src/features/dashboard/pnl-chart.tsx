"use client";

import { useQuery } from "@tanstack/react-query";
import { analyticsService } from "@/services/analytics.service";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { formatDateTime } from "@/lib/utils";

export function PnLChart() {
  const { data, isLoading } = useQuery({
    queryKey: ["analytics", "execution-records-chart"],
    queryFn: () => analyticsService.listExecutionRecords({ limit: 100 }),
  });

  if (isLoading) {
    return (
      <div className="h-48 flex items-center justify-center text-muted-foreground text-sm">
        Loading…
      </div>
    );
  }

  const records = data?.records ?? [];

  if (records.length === 0) {
    return (
      <div className="h-48 flex items-center justify-center text-muted-foreground text-sm">
        No execution data yet
      </div>
    );
  }

  const chartData = records.slice(-30).map((r) => ({
    label: formatDateTime(r.recorded_at).slice(0, 6),
    pnl: r.realized_pnl ?? 0,
  }));

  return (
    <ResponsiveContainer width="100%" height={192}>
      <BarChart data={chartData}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
        <XAxis dataKey="label" tick={{ fontSize: 10 }} tickLine={false} axisLine={false} />
        <YAxis
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={70}
          tickFormatter={(v: number) => `₹${(v / 1000).toFixed(0)}k`}
        />
        <Tooltip
          formatter={(v: number) => [`₹${v.toLocaleString("en-IN")}`, "PnL"]}
          contentStyle={{
            fontSize: 12,
            backgroundColor: "hsl(var(--popover))",
            border: "1px solid hsl(var(--border))",
          }}
        />
        <Bar dataKey="pnl" fill="#22c55e" radius={[2, 2, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
