"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { BulkMoveResponse, projectTasksApi } from "@/lib/api";
import { invalidateTaskCaches } from "@/hooks/invalidateTaskCaches";

export type SourceAction = "archive" | "mark_done";
export type SubtaskStrategy = "block" | "cascade" | "orphan";

// Stable error codes the backend can return. Surface the friendlier
// message in UI rather than the raw code.
const ERROR_MESSAGES: Record<string, string> = {
  cross_workspace_move: "Cross-workspace move isn't supported yet.",
  same_project_move: "That's already the source project.",
  target_project_not_found: "Target project not found.",
  task_already_archived: "Task is already archived — nothing to move.",
  task_has_subtasks: "This task has subtasks — pick a subtask strategy first.",
  source_task_not_found: "Task not found.",
  invalid_target_status: "Picked status doesn't exist on the destination board.",
};

function extractErrorCode(err: unknown): string | null {
  const e = err as { response?: { data?: { detail?: string } } };
  return e?.response?.data?.detail ?? null;
}

export function useTaskMove(opts: {
  workspaceId: string | null;
  sourceProjectId: string;
}) {
  const queryClient = useQueryClient();

  const single = useMutation({
    mutationFn: async (input: {
      taskId: string;
      target_project_id: string;
      source_action: SourceAction;
      subtask_strategy?: SubtaskStrategy;
      target_status_slug?: string;
    }) =>
      projectTasksApi.moveToProject(opts.sourceProjectId, input.taskId, {
        target_project_id: input.target_project_id,
        source_action: input.source_action,
        subtask_strategy: input.subtask_strategy ?? "block",
        ...(input.target_status_slug && {
          target_status_slug: input.target_status_slug,
        }),
      }),
    onSuccess: (newTask) => {
      invalidateTaskCaches(queryClient, opts.workspaceId);
      toast.success(`Moved to project — new task #${newTask.task_key}`);
    },
    onError: (err) => {
      const code = extractErrorCode(err);
      toast.error(code ? (ERROR_MESSAGES[code] ?? code) : "Move failed");
    },
  });

  const bulk = useMutation({
    mutationFn: async (input: {
      task_ids: string[];
      target_project_id: string;
      source_action: SourceAction;
      subtask_strategy?: SubtaskStrategy;
      target_status_slug?: string;
    }): Promise<BulkMoveResponse> =>
      projectTasksApi.bulkMoveToProject(opts.sourceProjectId, {
        task_ids: input.task_ids,
        target_project_id: input.target_project_id,
        source_action: input.source_action,
        subtask_strategy: input.subtask_strategy ?? "block",
        ...(input.target_status_slug && {
          target_status_slug: input.target_status_slug,
        }),
      }),
    onSuccess: (response) => {
      invalidateTaskCaches(queryClient, opts.workspaceId);
      const moved = response.results.filter((r) => r.status === "moved").length;
      const skipped = response.results.length - moved;
      if (skipped === 0) {
        toast.success(`Moved ${moved} task${moved === 1 ? "" : "s"}.`);
      } else {
        // Surface the first error code so the operator knows *why* skipped.
        const firstError = response.results.find((r) => r.error_code)?.error_code;
        const reason = firstError ? ERROR_MESSAGES[firstError] ?? firstError : "";
        toast.warning(
          `Moved ${moved}, skipped ${skipped}${reason ? ` — ${reason}` : ""}.`,
        );
      }
    },
    onError: () => {
      toast.error("Bulk move failed");
    },
  });

  return { single, bulk };
}
