"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { cn } from "@/lib/utils";
import { useShortcut } from "@/hooks/useKeyboardShortcuts";
import { taskConfigApi, TaskStatusConfig } from "@/lib/api";

export interface DeleteStatusModalProps {
  workspaceId: string;
  status: TaskStatusConfig;
  /** Other statuses in the same scope (workspace defaults or same project). */
  candidates: TaskStatusConfig[];
  onClose: () => void;
  onConfirm: (migrateTo: string | null) => Promise<void>;
  isDeleting: boolean;
}

/**
 * Confirm-delete modal that surfaces the task-migration choice. When the
 * status is unused, "Don't move anything" is offered as an explicit option;
 * when there are tasks, the operator must pick a target before delete is
 * enabled.
 */
export function DeleteStatusModal({
  workspaceId,
  status,
  candidates,
  onClose,
  onConfirm,
  isDeleting,
}: DeleteStatusModalProps) {
  const { data: usage, isLoading: usageLoading } = useQuery({
    queryKey: ["taskStatusUsage", workspaceId, status.id],
    queryFn: () => taskConfigApi.getStatusUsage(workspaceId, status.id),
  });
  const taskCount = usage?.count ?? 0;

  const eligible = candidates.filter((c) => c.id !== status.id);
  const [migrateTo, setMigrateTo] = useState<string>(() => {
    // Default to the first eligible status with the same category, falling
    // back to the first eligible regardless of category. Keeps "In Progress"
    // tasks landing in another "In Progress"-like column when possible.
    const sameCategory = eligible.find((c) => c.category === status.category);
    return sameCategory?.id ?? eligible[0]?.id ?? "";
  });

  // Once the count loads, refresh the default in case the operator already
  // changed it — we only seed on first render.
  useEffect(() => {
    if (!migrateTo && eligible.length > 0) {
      setMigrateTo(eligible[0].id);
    }
  }, [eligible, migrateTo]);

  useShortcut("escape", onClose, { enabled: !isDeleting });

  const confirmDisabled =
    isDeleting ||
    usageLoading ||
    (taskCount > 0 && !migrateTo);

  const handleConfirm = async () => {
    // If there are no tasks, the migrate_to query param is meaningless —
    // pass null so the backend takes the no-migration path.
    await onConfirm(taskCount > 0 ? migrateTo : null);
  };

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center bg-background/70 backdrop-blur-sm px-3 sm:px-0 pb-3 sm:pb-0"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.12 }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !isDeleting) onClose();
      }}
    >
      <motion.div
        initial={{ y: 24, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        exit={{ y: 24, opacity: 0 }}
        transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
        className="relative w-full max-w-md rounded-2xl border border-border bg-muted/95 backdrop-blur-xl shadow-2xl shadow-black/40 ring-1 ring-white/5"
      >
        <div className="flex items-start justify-between px-5 py-4 border-b border-border/60">
          <div className="flex items-center gap-3">
            <div className="rounded-full bg-red-500/10 p-2">
              <AlertTriangle className="h-4 w-4 text-red-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold tracking-tight text-foreground">
                Delete status
              </h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle"
                  style={{ backgroundColor: status.color }}
                />
                {status.name}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isDeleting}
            className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/40 transition-colors"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-5 py-4 space-y-3">
          {usageLoading ? (
            <div className="h-10 rounded-md bg-muted/40 animate-pulse" />
          ) : taskCount === 0 ? (
            <p className="text-sm text-muted-foreground">
              No tasks use this status. It will be deactivated and hidden from
              the board.
            </p>
          ) : (
            <>
              <p className="text-sm text-foreground">
                <span className="font-semibold">{taskCount}</span>{" "}
                {taskCount === 1 ? "task uses" : "tasks use"} this status. Move
                them to:
              </p>
              <div className="flex flex-col gap-1.5">
                <label
                  htmlFor="migrate-target"
                  className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground/80 font-medium"
                >
                  Target status
                </label>
                <select
                  id="migrate-target"
                  value={migrateTo}
                  onChange={(e) => setMigrateTo(e.target.value)}
                  className={cn(
                    "w-full bg-background/40 border border-border/70 rounded-md px-2 py-2",
                    "text-sm text-foreground",
                    "focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:border-primary-500/50",
                  )}
                  disabled={eligible.length === 0}
                >
                  {eligible.length === 0 ? (
                    <option value="">No other statuses available</option>
                  ) : (
                    eligible.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))
                  )}
                </select>
              </div>
              {eligible.length === 0 && (
                <p className="text-xs text-red-300">
                  Create another status before deleting this one — tasks need
                  somewhere to go.
                </p>
              )}
            </>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border/60 bg-background/40 rounded-b-2xl">
          <button
            type="button"
            onClick={onClose}
            disabled={isDeleting}
            className="px-3 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-accent/40 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={confirmDisabled || (taskCount > 0 && eligible.length === 0)}
            className={cn(
              "px-3.5 py-1.5 rounded-md text-xs font-semibold tracking-tight",
              "bg-red-500 text-white hover:bg-red-400 transition-colors",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "ring-1 ring-red-500/40",
            )}
          >
            {isDeleting ? "Deleting…" : "Delete status"}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
