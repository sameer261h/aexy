import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useTasksLayout } from "@/hooks/useTasksLayout";

describe("useTasksLayout", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns the fallback when no value is persisted", () => {
    const { result } = renderHook(() => useTasksLayout("test:project-1", "board"));
    expect(result.current[0]).toBe("board");
  });

  it("hydrates from localStorage on mount", () => {
    window.localStorage.setItem("aexy:tasksLayout:test:project-1", "table");
    const { result } = renderHook(() => useTasksLayout("test:project-1", "board"));
    expect(result.current[0]).toBe("table");
  });

  it("persists changes back to localStorage under the scoped key", () => {
    const { result } = renderHook(() => useTasksLayout("workspaceTasks", "board"));
    act(() => result.current[1]("table"));
    expect(window.localStorage.getItem("aexy:tasksLayout:workspaceTasks")).toBe(
      "table",
    );
  });

  it("ignores malformed stored values and stays on the fallback", () => {
    window.localStorage.setItem("aexy:tasksLayout:bogus", "kanban-3000");
    const { result } = renderHook(() => useTasksLayout("bogus", "board"));
    expect(result.current[0]).toBe("board");
  });

  it("keeps separate state across scope keys", () => {
    const a = renderHook(() => useTasksLayout("scope-a", "board"));
    const b = renderHook(() => useTasksLayout("scope-b", "board"));

    act(() => a.result.current[1]("table"));

    expect(window.localStorage.getItem("aexy:tasksLayout:scope-a")).toBe("table");
    expect(window.localStorage.getItem("aexy:tasksLayout:scope-b")).toBeNull();
    expect(b.result.current[0]).toBe("board");
  });
});
