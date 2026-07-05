"use client";

import { useQuery } from "@tanstack/react-query";
import { developerApi, MyAssignedTask } from "@/lib/api";

/**
 * All work items (tasks, bugs, stories) assigned to the current user, across the
 * three trackers — the unified "what's on my plate" view.
 */
export function useMyWork(params?: { status_filter?: string; include_done?: boolean }) {
  return useQuery<MyAssignedTask[]>({
    queryKey: ["myWork", params ?? {}],
    queryFn: () => developerApi.getMyAssignedTasks(params),
  });
}
