/**
 * Focused coverage for the CRM truthful-views slice: `useCRMRecords` must
 * call the server-side POST query endpoint (not the old GET list, which
 * silently ignored filters/sorts) and surface the server's `total` as-is.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

const queryMock = vi.fn();

vi.mock("@/lib/api", () => ({
  crmApi: {
    records: {
      query: (...args: unknown[]) => queryMock(...args),
    },
  },
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { useCRMRecords } from "@/hooks/useCRM";

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

beforeEach(() => {
  queryMock.mockReset();
});

describe("useCRMRecords", () => {
  it("sends filters, sorts, q, limit, and offset to the POST query endpoint", async () => {
    queryMock.mockResolvedValue({ records: [], total: 0, limit: 50, offset: 0 });

    renderHook(
      () =>
        useCRMRecords(WORKSPACE, OBJECT, {
          filters: [{ attribute: "stage", operator: "equals", value: "Lead" }],
          sorts: [{ attribute: "name", direction: "asc" }],
          q: "acme",
          limit: 50,
          offset: 50,
        }),
      { wrapper: makeWrapper() }
    );

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(1));

    expect(queryMock).toHaveBeenCalledWith(WORKSPACE, OBJECT, {
      filters: [{ attribute: "stage", operator: "equals", value: "Lead" }],
      sorts: [{ attribute: "name", direction: "asc" }],
      q: "acme",
      limit: 50,
      offset: 50,
    });
  });

  it("surfaces the server-reported total instead of the loaded array length", async () => {
    queryMock.mockResolvedValue({
      records: [{ id: "r1" }, { id: "r2" }],
      total: 137,
      limit: 2,
      offset: 0,
    });

    const { result } = renderHook(
      () => useCRMRecords(WORKSPACE, OBJECT, { limit: 2, offset: 0 }),
      { wrapper: makeWrapper() }
    );

    await waitFor(() => expect(result.current.total).toBe(137));
    expect(result.current.records).toHaveLength(2);
    expect(result.current.total).not.toBe(result.current.records.length);
  });

  it("issues a fresh request when offset changes (pagination)", async () => {
    queryMock.mockResolvedValue({ records: [], total: 5, limit: 2, offset: 0 });

    const { rerender } = renderHook(
      ({ offset }: { offset: number }) => useCRMRecords(WORKSPACE, OBJECT, { limit: 2, offset }),
      { wrapper: makeWrapper(), initialProps: { offset: 0 } }
    );

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(1));

    rerender({ offset: 2 });

    await waitFor(() => expect(queryMock).toHaveBeenCalledTimes(2));
    expect(queryMock).toHaveBeenLastCalledWith(WORKSPACE, OBJECT, { limit: 2, offset: 2 });
  });
});
