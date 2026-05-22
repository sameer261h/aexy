"use client";

import { useState } from "react";
import { AlertCircle, ArrowRight, RefreshCw } from "lucide-react";

import { useProjects } from "@/hooks/useProjects";
import { useTaskMove, SourceAction, SubtaskStrategy } from "@/hooks/useTaskMove";

export interface MoveToProjectModalProps {
  workspaceId: string;
  sourceProjectId: string;
  taskIds: string[];           // length 1 for single, N for bulk
  hasSubtasks: boolean;        // only meaningful for single
  onClose: () => void;
  onMoved?: () => void;
}

const SOURCE_ACTIONS: { value: SourceAction; label: string; hint: string }[] = [
  {
    value: "archive",
    label: "Archive original",
    hint: "Hide from boards. Restorable later from the archive view.",
  },
  {
    value: "mark_done",
    label: "Mark original as Done",
    hint: "Stays visible in the Done column with a link to the new task.",
  },
];

const SUBTASK_STRATEGIES: { value: SubtaskStrategy; label: string; hint: string }[] = [
  {
    value: "block",
    label: "Block the move",
    hint: "Refuse to move while subtasks exist (default — safest).",
  },
  {
    value: "cascade",
    label: "Move subtasks too",
    hint: "Clone every subtask into the new project under the new parent.",
  },
  {
    value: "orphan",
    label: "Leave subtasks behind",
    hint: "Subtasks remain in this project; their parent link points at the archived original.",
  },
];

/**
 * Move one or more tasks to another project in the same workspace. The
 * source task is forked into the destination project, linked back as
 * a "duplicates" dependency, and then archived or marked done at the
 * operator's choice. Used by both the task detail modal and the bulk
 * toolbar.
 */
export function MoveToProjectModal({
  workspaceId,
  sourceProjectId,
  taskIds,
  hasSubtasks,
  onClose,
  onMoved,
}: MoveToProjectModalProps) {
  const { projects, isLoading: projectsLoading } = useProjects(workspaceId);
  const { single, bulk } = useTaskMove({ workspaceId, sourceProjectId });

  const isBulk = taskIds.length > 1;
  const showSubtaskRadio = !isBulk && hasSubtasks;

  const candidates = projects.filter(
    (p) => p.id !== sourceProjectId && p.status !== "archived",
  );

  const [targetProjectId, setTargetProjectId] = useState<string>("");
  const [sourceAction, setSourceAction] = useState<SourceAction>("archive");
  const [subtaskStrategy, setSubtaskStrategy] = useState<SubtaskStrategy>("block");
  const [error, setError] = useState<string | null>(null);

  const submitting = single.isPending || bulk.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!targetProjectId) {
      setError("Pick a destination project.");
      return;
    }
    try {
      if (isBulk) {
        await bulk.mutateAsync({
          task_ids: taskIds,
          target_project_id: targetProjectId,
          source_action: sourceAction,
          subtask_strategy: "block",  // bulk skips per-task subtask handling
        });
      } else {
        await single.mutateAsync({
          taskId: taskIds[0],
          target_project_id: targetProjectId,
          source_action: sourceAction,
          subtask_strategy: showSubtaskRadio ? subtaskStrategy : "block",
        });
      }
      onMoved?.();
      onClose();
    } catch {
      // Toast already surfaces the error from the hook.
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-card rounded-xl w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <h3 className="text-xl font-semibold text-foreground mb-1">
          {isBulk
            ? `Move ${taskIds.length} tasks to another project`
            : "Move task to another project"}
        </h3>
        <p className="text-muted-foreground text-sm mb-5">
          A new task is created in the destination project and linked back
          to {isBulk ? "each original" : "this one"} as a duplicate.
        </p>

        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div>
              <label className="block text-sm text-muted-foreground mb-1">
                Destination project
              </label>
              {projectsLoading ? (
                <div className="h-10 bg-muted rounded-lg animate-pulse" />
              ) : candidates.length === 0 ? (
                <div className="text-sm text-muted-foreground bg-muted rounded-lg px-3 py-2">
                  No other projects in this workspace.
                </div>
              ) : (
                <select
                  value={targetProjectId}
                  onChange={(e) => setTargetProjectId(e.target.value)}
                  autoFocus
                  className="w-full px-3 py-2 bg-muted border border-border rounded-lg text-foreground focus:outline-none focus:border-primary-500"
                >
                  <option value="">Pick one…</option>
                  {candidates.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div>
              <label className="block text-sm text-muted-foreground mb-2">
                What happens to the original?
              </label>
              <div className="space-y-2">
                {SOURCE_ACTIONS.map((opt) => (
                  <label
                    key={opt.value}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition ${
                      sourceAction === opt.value
                        ? "border-primary-500 bg-primary-900/20"
                        : "border-border hover:border-foreground/30"
                    }`}
                  >
                    <input
                      type="radio"
                      name="source-action"
                      value={opt.value}
                      checked={sourceAction === opt.value}
                      onChange={() => setSourceAction(opt.value)}
                      className="mt-1"
                    />
                    <div>
                      <div className="text-foreground text-sm font-medium">
                        {opt.label}
                      </div>
                      <div className="text-xs text-muted-foreground">{opt.hint}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {showSubtaskRadio && (
              <div>
                <label className="block text-sm text-muted-foreground mb-2">
                  This task has subtasks
                </label>
                <div className="space-y-2">
                  {SUBTASK_STRATEGIES.map((opt) => (
                    <label
                      key={opt.value}
                      className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition ${
                        subtaskStrategy === opt.value
                          ? "border-primary-500 bg-primary-900/20"
                          : "border-border hover:border-foreground/30"
                      }`}
                    >
                      <input
                        type="radio"
                        name="subtask-strategy"
                        value={opt.value}
                        checked={subtaskStrategy === opt.value}
                        onChange={() => setSubtaskStrategy(opt.value)}
                        className="mt-1"
                      />
                      <div>
                        <div className="text-foreground text-sm font-medium">
                          {opt.label}
                        </div>
                        <div className="text-xs text-muted-foreground">{opt.hint}</div>
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {isBulk && (
              <p className="text-xs text-muted-foreground bg-muted/50 rounded-lg p-3">
                Bulk moves use the "block" subtask rule. Move tasks with
                subtasks individually if you need cascade or orphan handling.
              </p>
            )}

            {error && (
              <div className="flex items-center gap-2 text-red-400 text-sm">
                <AlertCircle className="h-4 w-4" />
                {error}
              </div>
            )}
          </div>

          <div className="flex gap-3 mt-6">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 bg-muted hover:bg-accent text-foreground rounded-lg transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !targetProjectId || candidates.length === 0}
              className="flex-1 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {submitting ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Moving…
                </>
              ) : (
                <>
                  <ArrowRight className="h-4 w-4" />
                  Move
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
