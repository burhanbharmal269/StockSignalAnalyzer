"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { authService } from "@/services/auth.service";
import { useAuth } from "@/hooks/use-auth";
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

export function SettingsView() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState<"profile" | "security">("profile");

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

  return (
    <div className="max-w-2xl space-y-6">
      <div className="flex gap-1 border-b">
        {(["profile", "security"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-sm capitalize -mb-px border-b-2 transition-colors ${
              activeTab === tab
                ? "border-primary text-foreground font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

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
