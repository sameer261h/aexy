/**
 * Focused coverage for the Tables truthful-views slice: `useTableRecords`
 * must call the server-side POST query endpoint (not the old GET list,
 * which silently ignored sort_by/sort_dir/filters) and surface the
 * server's `total` as-is.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const queryMock = vi.fn();

vi.mock("@/lib/api", () => ({
  tablesApi: {
    records: {
      query: (...args: unknown[]) => queryMock(...args),
    },
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { useTableRecords } from "@/hooks/useTables";

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
const TABLE = "table-1";

beforeEach(() => {
  queryMock.mockReset();
});

describe("useTableRecords", () => {
  it("sends filters, sorts, limit, and offset to the POST query endpoint", async () => {
    queryMock.mockResolvedValue({ records: [], total: 0, limit: 50, offset: 0 });

    renderHook(
      () =>
        useTableRecords(WORKSPACE, TABLE, {
          filters: [{ attribute: "status", operator: "equals", value: "Done" }],
          sorts: [{ attribute: "name", direction: "asc" }],
          limit: 50,
          offset: 50,
        }),
      { wrapper: makeWrapper() }
    );

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(1));

    expect(queryMock).toHaveBeenCalledWith(WORKSPACE, TABLE, {
      filters: [{ attribute: "status", operator: "equals", value: "Done" }],
      sorts: [{ attribute: "name", direction: "asc" }],
      limit: 50,
      offset: 50,
    });
  });

  it("surfaces the server-reported total instead of the loaded array length", async () => {
    queryMock.mockResolvedValue({
      records: [{ id: "r1" }, { id: "r2" }],
      total: 214,
      limit: 2,
      offset: 0,
    });

    const { result } = renderHook(
      () => useTableRecords(WORKSPACE, TABLE, { limit: 2, offset: 0 }),
      { wrapper: makeWrapper() }
    );

    await waitFor(() => expect(result.current.total).toBe(214));
    expect(result.current.records).toHaveLength(2);
    expect(result.current.total).not.toBe(result.current.records.length);
  });

  it("issues a fresh request when offset changes (pagination)", async () => {
    queryMock.mockResolvedValue({ records: [], total: 5, limit: 2, offset: 0 });

    const { rerender } = renderHook(
      ({ offset }: { offset: number }) => useTableRecords(WORKSPACE, TABLE, { limit: 2, offset }),
      { wrapper: makeWrapper(), initialProps: { offset: 0 } }
    );

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(1));

    rerender({ offset: 2 });

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(2));
    expect(queryMock).toHaveBeenLastCalledWith(WORKSPACE, TABLE, { limit: 2, offset: 2 });
  });

  it("sends q to the POST query endpoint for server-side search", async () => {
    queryMock.mockResolvedValue({ records: [], total: 0, limit: 50, offset: 0 });

    renderHook(
      () => useTableRecords(WORKSPACE, TABLE, { q: "Acme" }),
      { wrapper: makeWrapper() }
    );

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(1));
    expect(queryMock).toHaveBeenCalledWith(WORKSPACE, TABLE, { q: "Acme" });
  });

  it("omits q from the body when undefined", async () => {
    queryMock.mockResolvedValue({ records: [], total: 0, limit: 50, offset: 0 });

    renderHook(
      () => useTableRecords(WORKSPACE, TABLE, {}),
      { wrapper: makeWrapper() }
    );

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(1));
    expect(queryMock).toHaveBeenCalledWith(WORKSPACE, TABLE, {});
  });

  it("includes q in query identity and sends the newest search", async () => {
    queryMock.mockResolvedValue({ records: [], total: 0, limit: 50, offset: 0 });

    const { rerender } = renderHook(
      ({ q }: { q?: string }) => useTableRecords(WORKSPACE, TABLE, { q }),
      { wrapper: makeWrapper(), initialProps: { q: "Acme" } }
    );

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(1));
    rerender({ q: "Beta" });
    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(2));

    expect(queryMock).toHaveBeenLastCalledWith(WORKSPACE, TABLE, { q: "Beta" });
  });

  it("keeps filters and sorts alongside server search", async () => {
    queryMock.mockResolvedValue({ records: [], total: 0, limit: 50, offset: 0 });

    renderHook(
      () =>
        useTableRecords(WORKSPACE, TABLE, {
          q: "Acme",
          filters: [{ attribute: "status", operator: "equals", value: "open" }],
          sorts: [{ attribute: "name", direction: "asc" }],
        }),
      { wrapper: makeWrapper() }
    );

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(1));
    expect(queryMock).toHaveBeenCalledWith(WORKSPACE, TABLE, {
      q: "Acme",
      filters: [{ attribute: "status", operator: "equals", value: "open" }],
      sorts: [{ attribute: "name", direction: "asc" }],
    });
  });
});
