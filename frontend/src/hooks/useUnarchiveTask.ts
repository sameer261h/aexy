"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { projectTasksApi } from "@/lib/api";
import { invalidateTaskCaches } from "@/hooks/invalidateTaskCaches";

/**
 * Restore an archived task. The restored task lands back in the project board
 * with its original status slug intact (no remap needed — archiving doesn't
 * change the status, just hides the row).
 */
export function useUnarchiveTask(workspaceId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ teamId, taskId }: { teamId: string; taskId: string }) =>
      projectTasksApi.unarchive(teamId, taskId),
    onSuccess: () => {
      invalidateTaskCaches(queryClient, workspaceId);
      toast.success("Task restored");
    },
    onError: () => {
      toast.error("Failed to unarchive task");
    },
  });
}
