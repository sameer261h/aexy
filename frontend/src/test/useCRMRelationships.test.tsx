/**
 * Focused coverage for the read-only relationship navigation hooks:
 * they must call the new relationship endpoints with the right shape and
 * surface server totals as-is (not the loaded array length).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const getRelationshipsMock = vi.fn();
const getBacklinksMock = vi.fn();
const searchCandidatesMock = vi.fn();

vi.mock("@/lib/api", () => ({
  crmApi: {
    relationships: {
      get: (...args: unknown[]) => getRelationshipsMock(...args),
      backlinks: (...args: unknown[]) => getBacklinksMock(...args),
      searchCandidates: (...args: unknown[]) => searchCandidatesMock(...args),
    },
  },
}));

import {
  useRecordRelationships,
  useRecordBacklinks,
  useRelationshipCandidates,
} from "@/hooks/useCRMRelationships";

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
}

const WORKSPACE = "ws-1";
const OBJECT = "obj-1";
const RECORD = "rec-1";

beforeEach(() => {
  getRelationshipsMock.mockReset();
  getBacklinksMock.mockReset();
  searchCandidatesMock.mockReset();
});

describe("useRecordRelationships", () => {
  it("calls the relationships endpoint with workspace/object/record IDs", async () => {
    getRelationshipsMock.mockResolvedValue({ groups: [] });
    renderHook(() => useRecordRelationships(WORKSPACE, OBJECT, RECORD), { wrapper: makeWrapper() });
    await waitFor(() => expect(getRelationshipsMock).toHaveBeenCalledWith(WORKSPACE, OBJECT, RECORD));
  });

  it("surfaces resolved groups from the server response", async () => {
    getRelationshipsMock.mockResolvedValue({
      groups: [{ attribute_id: "a1", attribute_name: "Company", target_object_id: "obj-2", allow_multiple: false, total: 1, items: [] }],
    });
    const { result } = renderHook(() => useRecordRelationships(WORKSPACE, OBJECT, RECORD), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.groups).toHaveLength(1));
  });
});

describe("useRecordBacklinks", () => {
  it("surfaces the server-reported total instead of the loaded item count", async () => {
    getBacklinksMock.mockResolvedValue({
      items: [{ record_id: "r1" }],
      total: 47,
      limit: 20,
      offset: 0,
    });
    const { result } = renderHook(
      () => useRecordBacklinks(WORKSPACE, OBJECT, RECORD, { limit: 20, offset: 0 }),
      { wrapper: makeWrapper() }
    );
    await waitFor(() => expect(result.current.total).toBe(47));
    expect(result.current.items).toHaveLength(1);
    expect(result.current.total).not.toBe(result.current.items.length);
  });

  it("passes limit/offset through to the backlinks endpoint", async () => {
    getBacklinksMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 20 });
    renderHook(
      () => useRecordBacklinks(WORKSPACE, OBJECT, RECORD, { limit: 20, offset: 20 }),
      { wrapper: makeWrapper() }
    );
    await waitFor(() =>
      expect(getBacklinksMock).toHaveBeenCalledWith(WORKSPACE, OBJECT, RECORD, { limit: 20, offset: 20 })
    );
  });
});

describe("useRelationshipCandidates", () => {
  it("sends target_object_id, q, and exclusion fields to the candidate search endpoint", async () => {
    searchCandidatesMock.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    renderHook(
      () =>
        useRelationshipCandidates(WORKSPACE, OBJECT, {
          target_object_id: "obj-2",
          q: "acme",
          exclude_record_id: RECORD,
          exclude_ids: ["r2", "r3"],
        }),
      { wrapper: makeWrapper() }
    );
    await waitFor(() =>
      expect(searchCandidatesMock).toHaveBeenCalledWith(WORKSPACE, OBJECT, {
        target_object_id: "obj-2",
        q: "acme",
        exclude_record_id: RECORD,
        exclude_ids: ["r2", "r3"],
      })
    );
  });

  it("does not query when disabled", async () => {
    renderHook(
      () =>
        useRelationshipCandidates(
          WORKSPACE, OBJECT, { target_object_id: "obj-2" }, false,
        ),
      { wrapper: makeWrapper() }
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(searchCandidatesMock).not.toHaveBeenCalled();
  });

  it("does not query when target_object_id is missing", async () => {
    renderHook(
      () => useRelationshipCandidates(WORKSPACE, OBJECT, { target_object_id: null }),
      { wrapper: makeWrapper() }
    );
    await new Promise((r) => setTimeout(r, 50));
    expect(searchCandidatesMock).not.toHaveBeenCalled();
  });
});
