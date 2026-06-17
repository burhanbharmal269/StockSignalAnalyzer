"use client";

import { useState } from "react";
import { Lock, Unlock, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { executionService } from "@/services/execution.service";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";

export function ExecutionLockButton() {
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const { data: status } = useQuery({
    queryKey: ["execution-status"],
    queryFn: executionService.getStatus,
    refetchInterval: 15_000,
  });

  const lockMutation = useMutation({
    mutationFn: () => executionService.lock("Emergency lock from dashboard"),
    onSuccess: () => {
      toast.warning("Execution LOCKED — signals continue, orders halted");
      qc.invalidateQueries({ queryKey: ["execution-status"] });
      setConfirming(false);
    },
  });

  const unlockMutation = useMutation({
    mutationFn: () => executionService.unlock("Manually unlocked from dashboard"),
    onSuccess: () => {
      toast.success("Execution UNLOCKED");
      qc.invalidateQueries({ queryKey: ["execution-status"] });
    },
  });

  const isLocked = status?.locked ?? false;
  const isAutomatic = status?.execution_mode === "AUTOMATIC";

  if (isLocked) {
    return (
      <button
        onClick={() => unlockMutation.mutate()}
        disabled={unlockMutation.isPending}
        className="flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium bg-warning/10 text-warning border border-warning/30 hover:bg-warning/20"
      >
        <Lock className="h-3.5 w-3.5" />
        LOCKED
      </button>
    );
  }

  if (confirming) {
    return (
      <div className="flex items-center gap-1">
        <span className="text-xs text-warning">Lock orders?</span>
        <button
          onClick={() => lockMutation.mutate()}
          className="text-xs rounded px-2 py-1 bg-warning text-warning-foreground hover:bg-warning/90"
        >
          Yes
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="text-xs rounded px-2 py-1 bg-muted hover:bg-muted/80"
        >
          No
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => isAutomatic ? setConfirming(true) : undefined}
      title={isAutomatic ? "Lock order execution" : "Order execution already gated by MANUAL mode"}
      className={cn(
        "flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium border transition-colors",
        isAutomatic
          ? "border-border text-muted-foreground hover:bg-muted cursor-pointer"
          : "border-border text-muted-foreground opacity-50 cursor-default"
      )}
    >
      <Unlock className="h-3.5 w-3.5" />
      UNLOCKED
    </button>
  );
}

// Keep old export name for backward compat
export function KillSwitchButton() {
  return <ExecutionLockButton />;
}
