import type { QueryClient } from "@tanstack/react-query";

/**
 * Invalidate every React Query cache that holds task rows for a workspace.
 * Use this from any mutation that moves tasks between status_ids, sprints,
 * teams, or workspaces — drag-drop, bulk update, create, delete-with-migration.
 *
 * Keys touched today:
 *  - `["workspaceTasks", workspaceId]` — `/sprints?tab=tasks` board
 *  - `["sprintTasks"]` — every sprint board (unscoped; could be scoped per
 *     sprint once consumers cooperate)
 *  - `["projectTasks"]` — every project backlog/board
 *
 * Centralised because three different mutations would otherwise drift.
 */
export function invalidateTaskCaches(
  queryClient: QueryClient,
  workspaceId: string | null,
): void {
  if (workspaceId) {
    queryClient.invalidateQueries({ queryKey: ["workspaceTasks", workspaceId] });
  }
  queryClient.invalidateQueries({ queryKey: ["sprintTasks"] });
  queryClient.invalidateQueries({ queryKey: ["projectTasks"] });
}
