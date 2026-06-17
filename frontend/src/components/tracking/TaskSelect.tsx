"use client";

import { useTranslations } from "next-intl";
import { useTrackerCandidateTasks } from "@/hooks/useTrackerTimesheet";

// Lightweight task picker for correcting an inferred entry's attribution.
// Native <select> keeps it accessible + dependency-free; the candidate list is
// the caller's open assigned tasks (≤25), so no search/virtualization needed.
export function TaskSelect({
  value,
  onSelect,
  disabled,
}: {
  value?: string | null;
  onSelect: (taskId: string) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("tracking.tracker");
  const { data: tasks, isLoading } = useTrackerCandidateTasks();
  const hasTasks = (tasks?.length ?? 0) > 0;

  return (
    <select
      aria-label={t("reassignPlaceholder")}
      disabled={disabled || isLoading || !hasTasks}
      value={value ?? ""}
      onChange={(e) => {
        if (e.target.value) onSelect(e.target.value);
      }}
      className="max-w-[12rem] rounded-lg border border-gray-300 bg-transparent px-2 py-1 text-xs outline-none focus:border-blue-500 disabled:opacity-50 dark:border-gray-700"
    >
      <option value="" disabled>
        {hasTasks ? t("reassignPlaceholder") : t("noTasks")}
      </option>
      {(tasks ?? []).map((task) => (
        <option key={task.id} value={task.id}>
          {task.title}
        </option>
      ))}
    </select>
  );
}
