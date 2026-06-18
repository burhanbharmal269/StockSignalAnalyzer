"use client";

import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { authService } from "@/services/auth.service";
import { useAuth } from "@/hooks/use-auth";
import { useRiskCapitalSettings, useUpdateRiskCapital } from "@/hooks/use-settings";
import type { RiskCapitalSettings } from "@/services/settings.service";
import { Loader2 } from "lucide-react";

const passwordSchema = z
  .object({
    old_password: z.string().min(1, "Required"),
    new_password: z.string().min(8, "Min 8 characters"),
    confirm_password: z.string().min(1, "Required"),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    path: ["confirm_password"],
    message: "Passwords do not match",
  });

type PasswordFormValues = z.infer<typeof passwordSchema>;

type Tab = "profile" | "trading" | "security";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="text-sm font-medium">{label}</label>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {children}
    </div>
  );
}

function Input({
  value,
  onChange,
  type = "number",
  min,
  max,
  step,
  prefix,
  suffix,
}: {
  value: string | number;
  onChange: (v: number) => void;
  type?: string;
  min?: number;
  max?: number;
  step?: number;
  prefix?: string;
  suffix?: string;
}) {
  return (
    <div className="flex items-center gap-1">
      {prefix && <span className="text-sm text-muted-foreground">{prefix}</span>}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        min={min}
        max={max}
        step={step}
        className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
      {suffix && <span className="text-sm text-muted-foreground">{suffix}</span>}
    </div>
  );
}

function TradingSettings() {
  const { data, isLoading } = useRiskCapitalSettings();
  const update = useUpdateRiskCapital();
  const [form, setForm] = useState<RiskCapitalSettings | null>(null);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (data && !form) {
      setForm(data);
    }
  }, [data, form]);

  function set<K extends keyof RiskCapitalSettings>(key: K, value: number) {
    setForm((f) => f ? { ...f, [key]: value } : f);
    setDirty(true);
  }

  function handleSave() {
    if (!form) return;
    update.mutate(form, {
      onSuccess: () => {
        toast.success("Settings saved — active on next scan cycle");
        setDirty(false);
      },
      onError: () => toast.error("Failed to save settings"),
    });
  }

  function handleReset() {
    if (data) {
      setForm(data);
      setDirty(false);
    }
  }

  if (isLoading || !form) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const absDaily = Math.round((form.total_capital * form.daily_loss_pct) / 100);
  const absWeekly = Math.round((form.total_capital * form.weekly_loss_pct) / 100);
  const perTrade = Math.round((form.total_capital * form.risk_per_trade_pct) / 100);

  return (
    <div className="space-y-6">
      {/* Capital */}
      <div className="rounded-lg border bg-card p-6 space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Capital</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Total trading capital — all position sizing and loss limits are calculated from this.
          </p>
        </div>
        <Field label="Total Capital (₹)" hint="Your actual trading capital in Indian Rupees">
          <Input
            value={form.total_capital}
            onChange={(v) => set("total_capital", Math.round(v))}
            min={10000}
            max={100000000}
            step={10000}
            prefix="₹"
          />
        </Field>
        <div className="rounded-md bg-muted/40 px-4 py-2 text-xs text-muted-foreground space-y-1">
          <p>Risk per trade: ₹{perTrade.toLocaleString("en-IN")} ({form.risk_per_trade_pct}%)</p>
          <p>Daily stop: ₹{absDaily.toLocaleString("en-IN")} ({form.daily_loss_pct}%)</p>
          <p>Weekly stop: ₹{absWeekly.toLocaleString("en-IN")} ({form.weekly_loss_pct}%)</p>
        </div>
      </div>

      {/* Risk per trade */}
      <div className="rounded-lg border bg-card p-6 space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Per-Trade Risk</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            How much capital can be lost on any single trade. Best practice: 1–2% for retail accounts.
          </p>
        </div>
        <Field label="Risk per Trade (%)" hint="% of total capital risked on each trade (option premium at risk)">
          <Input
            value={form.risk_per_trade_pct}
            onChange={(v) => set("risk_per_trade_pct", v)}
            min={0.1}
            max={10}
            step={0.1}
            suffix="%"
          />
        </Field>
      </div>

      {/* Loss limits */}
      <div className="rounded-lg border bg-card p-6 space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Loss Limits</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Breaching either the % or the absolute INR limit triggers the protection. Set both relative to your capital.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Daily Loss Cap (%)" hint="Stop trading for the day beyond this loss">
            <Input
              value={form.daily_loss_pct}
              onChange={(v) => set("daily_loss_pct", v)}
              min={0.5}
              max={20}
              step={0.5}
              suffix="%"
            />
          </Field>
          <Field label="Daily Loss Cap (₹)" hint="Absolute INR hard stop (whichever triggers first)">
            <Input
              value={form.daily_loss_abs}
              onChange={(v) => set("daily_loss_abs", Math.round(v))}
              min={100}
              max={form.total_capital}
              step={500}
              prefix="₹"
            />
          </Field>
          <Field label="Weekly Loss Cap (%)" hint="Rolling 5-day loss limit">
            <Input
              value={form.weekly_loss_pct}
              onChange={(v) => set("weekly_loss_pct", v)}
              min={0.5}
              max={50}
              step={0.5}
              suffix="%"
            />
          </Field>
          <Field label="Weekly Loss Cap (₹)">
            <Input
              value={form.weekly_loss_abs}
              onChange={(v) => set("weekly_loss_abs", Math.round(v))}
              min={100}
              max={form.total_capital}
              step={1000}
              prefix="₹"
            />
          </Field>
        </div>
      </div>

      {/* Position limits */}
      <div className="rounded-lg border bg-card p-6 space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Position Limits</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Controls concentration and the total number of concurrent open positions.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field label="Max Open Positions" hint="Hard cap on concurrent open positions">
            <Input
              value={form.max_open_positions}
              onChange={(v) => set("max_open_positions", Math.round(v))}
              min={1}
              max={50}
              step={1}
            />
          </Field>
          <Field label="Max Capital per Underlying (%)" hint="Max % of total capital in one underlying (e.g. NIFTY)">
            <Input
              value={form.max_capital_per_underlying_pct}
              onChange={(v) => set("max_capital_per_underlying_pct", v)}
              min={5}
              max={100}
              step={5}
              suffix="%"
            />
          </Field>
        </div>
      </div>

      {/* Volatility block */}
      <div className="rounded-lg border bg-card p-6 space-y-4">
        <div>
          <h2 className="text-sm font-semibold">Volatility Guard</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Blocks new positions when India VIX spikes above this level. Recommended: 20–25 for retail.
          </p>
        </div>
        <Field label="India VIX Block Threshold" hint="New positions blocked when VIX is above this value">
          <Input
            value={form.vix_threshold}
            onChange={(v) => set("vix_threshold", v)}
            min={10}
            max={80}
            step={1}
          />
        </Field>
      </div>

      {/* Save */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={!dirty || update.isPending}
          className="flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-5 py-2 text-sm font-medium hover:bg-primary/90 disabled:opacity-40"
        >
          {update.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
          Save Settings
        </button>
        {dirty && (
          <button
            onClick={handleReset}
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            Reset
          </button>
        )}
        {dirty && (
          <span className="text-xs text-warning">Unsaved changes</span>
        )}
      </div>
    </div>
  );
}

export function SettingsView() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>("trading");

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PasswordFormValues>({ resolver: zodResolver(passwordSchema) });

  const onChangePassword = async (values: PasswordFormValues) => {
    try {
      await authService.changePassword(values.old_password, values.new_password);
      toast.success("Password changed");
      reset();
    } catch {
      toast.error("Failed to change password");
    }
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "trading", label: "Trading" },
    { id: "profile", label: "Profile" },
    { id: "security", label: "Security" },
  ];

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex gap-1 border-b">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm -mb-px border-b-2 transition-colors ${
              activeTab === tab.id
                ? "border-primary text-foreground font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "trading" && <TradingSettings />}

      {activeTab === "profile" && user && (
        <div className="rounded-lg border bg-card p-6 space-y-4">
          <h2 className="text-sm font-medium">Profile</h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground block text-xs mb-1">Username</span>
              <span className="font-medium">{user.username}</span>
            </div>
            <div>
              <span className="text-muted-foreground block text-xs mb-1">Role</span>
              <span className="font-medium uppercase">{user.role}</span>
            </div>
          </div>
        </div>
      )}

      {activeTab === "security" && (
        <div className="rounded-lg border bg-card p-6 space-y-4">
          <h2 className="text-sm font-medium">Change Password</h2>
          <form onSubmit={handleSubmit(onChangePassword)} className="space-y-4">
            <div className="space-y-1">
              <label className="text-sm">Current Password</label>
              <input
                type="password"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                {...register("old_password")}
              />
              {errors.old_password && <p className="text-xs text-destructive">{errors.old_password.message}</p>}
            </div>
            <div className="space-y-1">
              <label className="text-sm">New Password</label>
              <input
                type="password"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                {...register("new_password")}
              />
              {errors.new_password && <p className="text-xs text-destructive">{errors.new_password.message}</p>}
            </div>
            <div className="space-y-1">
              <label className="text-sm">Confirm Password</label>
              <input
                type="password"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                {...register("confirm_password")}
              />
              {errors.confirm_password && <p className="text-xs text-destructive">{errors.confirm_password.message}</p>}
            </div>
            <button
              type="submit"
              disabled={isSubmitting}
              className="flex items-center gap-2 rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
              Change Password
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
