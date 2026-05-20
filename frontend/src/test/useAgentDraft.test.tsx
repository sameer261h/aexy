/**
 * Tests for `useAgentDraft` (UX-DEF-003).
 *
 * The hook is small but every piece is load-bearing:
 *
 * - hydrates from `agentsApi.getAgentDraft` on mount; 404 = no
 *   draft, not an error.
 * - debounces save() so typing doesn't pummel the server.
 * - clear() cancels any pending debounced save BEFORE firing
 *   DELETE — otherwise the debounced save could resurrect the
 *   row we just removed.
 * - the cleanup effect flushes a pending save on unmount so a
 *   navigation away doesn't lose the most recent keystroke.
 * - lastSavedAt drives the "saved Xs ago" UI; must update on
 *   every save.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useAgentDraft } from "@/hooks/useAgentDraft";
import * as apiModule from "@/lib/api";

const WORKSPACE = "ws-1";


beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});


afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});


// ---------------------------------------------------------------------------
// Hydration
// ---------------------------------------------------------------------------


describe("useAgentDraft — hydration", () => {
  it("fetches the server draft on mount", async () => {
    const getSpy = vi
      .spyOn(apiModule.agentsApi, "getAgentDraft")
      .mockResolvedValue({
        id: "draft-1",
        payload: { step: 3, name: "WIP" },
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-01T00:01:00Z",
      });

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));

    await waitFor(() => {
      expect(result.current.serverDraft?.id).toBe("draft-1");
    });
    expect(getSpy).toHaveBeenCalledWith(WORKSPACE);
    expect(result.current.lastSavedAt).toBe("2025-01-01T00:01:00Z");
    expect(result.current.error).toBe(null);
  });

  it("treats null (404 on server) as 'no draft, no error'", async () => {
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockResolvedValue(null);

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });
    expect(result.current.serverDraft).toBe(null);
    expect(result.current.error).toBe(null);
    expect(result.current.lastSavedAt).toBe(null);
  });

  it("does not fetch when workspace is null", () => {
    const getSpy = vi.spyOn(apiModule.agentsApi, "getAgentDraft");
    renderHook(() => useAgentDraft(null));
    expect(getSpy).not.toHaveBeenCalled();
  });

  it("does not fetch when enabled is false (wizard closed)", () => {
    const getSpy = vi.spyOn(apiModule.agentsApi, "getAgentDraft");
    renderHook(() => useAgentDraft(WORKSPACE, false));
    expect(getSpy).not.toHaveBeenCalled();
  });

  it("surfaces fetch errors via the error field", async () => {
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockRejectedValue(
      new Error("network down"),
    );

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));

    await waitFor(() => {
      expect(result.current.error).toContain("network down");
    });
  });
});


// ---------------------------------------------------------------------------
// Save debounce
// ---------------------------------------------------------------------------


describe("useAgentDraft — save debounce", () => {
  it("coalesces rapid save() calls into one network round-trip", async () => {
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockResolvedValue(null);
    const saveSpy = vi
      .spyOn(apiModule.agentsApi, "saveAgentDraft")
      .mockResolvedValue({
        id: "d",
        payload: {},
        created_at: "",
        updated_at: "2025-01-01T00:00:05Z",
      });

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.save({ step: 1 });
      result.current.save({ step: 2 });
      result.current.save({ step: 3 });
    });

    // Before the debounce timer fires, nothing should have hit the
    // network.
    expect(saveSpy).not.toHaveBeenCalled();

    // Advance past the 1200ms debounce window.
    await act(async () => {
      vi.advanceTimersByTime(1300);
    });

    await waitFor(() => {
      expect(saveSpy).toHaveBeenCalledTimes(1);
    });
    // The LAST payload won — only the most recent keystroke gets sent.
    expect(saveSpy).toHaveBeenCalledWith(WORKSPACE, { step: 3 });
  });

  it("updates lastSavedAt on each successful save", async () => {
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockResolvedValue(null);
    vi.spyOn(apiModule.agentsApi, "saveAgentDraft").mockResolvedValue({
      id: "d",
      payload: {},
      created_at: "",
      updated_at: "2025-02-02T10:00:00Z",
    });

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.save({ x: 1 });
    });
    await act(async () => {
      vi.advanceTimersByTime(1300);
    });

    await waitFor(() => {
      expect(result.current.lastSavedAt).toBe("2025-02-02T10:00:00Z");
    });
  });

  it("flips isSaving while a save is in flight", async () => {
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockResolvedValue(null);
    let resolveSave: (value: unknown) => void = () => undefined;
    vi.spyOn(apiModule.agentsApi, "saveAgentDraft").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSave = resolve as typeof resolveSave;
        }),
    );

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.save({ x: 1 });
    });
    await act(async () => {
      vi.advanceTimersByTime(1300);
    });

    await waitFor(() => {
      expect(result.current.isSaving).toBe(true);
    });

    act(() => {
      resolveSave({
        id: "d",
        payload: {},
        created_at: "",
        updated_at: "2025-01-01T00:00:00Z",
      });
    });

    await waitFor(() => {
      expect(result.current.isSaving).toBe(false);
    });
  });

  it("surfaces save errors via the error field", async () => {
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockResolvedValue(null);
    vi.spyOn(apiModule.agentsApi, "saveAgentDraft").mockRejectedValue(
      new Error("server full"),
    );

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.save({ x: 1 });
    });
    await act(async () => {
      vi.advanceTimersByTime(1300);
    });

    await waitFor(() => {
      expect(result.current.error).toContain("server full");
    });
  });

  it("no-ops save() when workspace is null", async () => {
    const saveSpy = vi.spyOn(apiModule.agentsApi, "saveAgentDraft");
    const { result } = renderHook(() => useAgentDraft(null));

    act(() => {
      result.current.save({ x: 1 });
    });
    await act(async () => {
      vi.advanceTimersByTime(1300);
    });

    expect(saveSpy).not.toHaveBeenCalled();
  });
});


// ---------------------------------------------------------------------------
// Clear semantics
// ---------------------------------------------------------------------------


describe("useAgentDraft — clear", () => {
  it("cancels a pending save BEFORE firing delete", async () => {
    // This is the critical invariant: if a debounced save is still
    // pending when the user successfully creates the agent, clear()
    // must NOT let that save fire (it would resurrect the row we're
    // about to delete).
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockResolvedValue(null);
    const saveSpy = vi
      .spyOn(apiModule.agentsApi, "saveAgentDraft")
      .mockResolvedValue({
        id: "d",
        payload: {},
        created_at: "",
        updated_at: "",
      });
    const deleteSpy = vi
      .spyOn(apiModule.agentsApi, "deleteAgentDraft")
      .mockResolvedValue(undefined);

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.save({ x: 1 });
    });
    // Don't advance time — leave the save pending.

    await act(async () => {
      await result.current.clear();
    });

    // Advance past the debounce window — the pending save must NOT
    // fire because clear() cancelled it.
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });

    expect(saveSpy).not.toHaveBeenCalled();
    expect(deleteSpy).toHaveBeenCalledWith(WORKSPACE);
  });

  it("clears serverDraft + lastSavedAt on success", async () => {
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockResolvedValue({
      id: "d",
      payload: { step: 1 },
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:01:00Z",
    });
    vi.spyOn(apiModule.agentsApi, "deleteAgentDraft").mockResolvedValue(
      undefined,
    );

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));
    await waitFor(() => expect(result.current.serverDraft).not.toBeNull());

    await act(async () => {
      await result.current.clear();
    });

    expect(result.current.serverDraft).toBe(null);
    expect(result.current.lastSavedAt).toBe(null);
  });

  it("surfaces delete errors via the error field", async () => {
    vi.spyOn(apiModule.agentsApi, "getAgentDraft").mockResolvedValue(null);
    vi.spyOn(apiModule.agentsApi, "deleteAgentDraft").mockRejectedValue(
      new Error("forbidden"),
    );

    const { result } = renderHook(() => useAgentDraft(WORKSPACE));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.clear();
    });

    expect(result.current.error).toContain("forbidden");
  });
});
