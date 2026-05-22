"use client";

import { useCallback, useEffect, useState } from "react";

export type TasksLayout = "board" | "table";

const STORAGE_PREFIX = "aexy:tasksLayout:";

/**
 * Persist the user's "board vs table" preference per scope (per-project for
 * the kanban page, "workspace" for the All Tasks tab). Reads lazily after
 * mount so SSR rendering matches the default; flips to the stored value on
 * the first client effect.
 */
export function useTasksLayout(scopeKey: string, fallback: TasksLayout = "board") {
  const storageKey = `${STORAGE_PREFIX}${scopeKey}`;
  const [layout, setLayoutState] = useState<TasksLayout>(fallback);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (stored === "board" || stored === "table") {
        setLayoutState(stored);
      }
    } catch {
      // localStorage unavailable — keep the fallback.
    }
  }, [storageKey]);

  const setLayout = useCallback(
    (next: TasksLayout) => {
      setLayoutState(next);
      try {
        if (typeof window !== "undefined") {
          window.localStorage.setItem(storageKey, next);
        }
      } catch {
        // localStorage unavailable — non-fatal; UI stays in sync this session.
      }
    },
    [storageKey],
  );

  return [layout, setLayout] as const;
}
