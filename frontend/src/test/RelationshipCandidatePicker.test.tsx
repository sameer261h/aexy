import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RelationshipCandidatePicker } from "@/components/crm/relationships/RelationshipCandidatePicker";

const useRelationshipCandidatesMock = vi.fn();

vi.mock("@/hooks/useCRMRelationships", () => ({
  useRelationshipCandidates: (...args: unknown[]) => useRelationshipCandidatesMock(...args),
}));

function lastQuerySeenByHook(): string | undefined {
  const lastCall = useRelationshipCandidatesMock.mock.calls.at(-1);
  return lastCall?.[2]?.q;
}

describe("RelationshipCandidatePicker", () => {
  beforeEach(() => {
    useRelationshipCandidatesMock.mockReset();
    useRelationshipCandidatesMock.mockReturnValue({
      items: [
        { record_id: "r1", record_label: "Acme Corp", is_archived: false },
        { record_id: "r2", record_label: "Beta Inc", is_archived: false },
      ],
      total: 2,
      limit: 20,
      offset: 0,
      isLoading: false,
      error: null,
    });
  });

  it("debounces the search query before it reaches the candidates hook", async () => {
    render(
      <RelationshipCandidatePicker
        workspaceId="ws-1"
        objectId="obj-1"
        targetObjectId="obj-2"
        onSelect={vi.fn()}
      />
    );

    fireEvent.change(screen.getByPlaceholderText("Search records…"), { target: { value: "Ac" } });

    // Immediately after typing, the debounced value hasn't flushed yet.
    expect(lastQuerySeenByHook()).toBeUndefined();

    // Real 300ms debounce -- wait past it, not an instant assertion.
    await waitFor(() => expect(lastQuerySeenByHook()).toBe("Ac"), { timeout: 1000 });
  }, 2000);

  it("shows candidate results and calls onSelect without persisting the selection", async () => {
    const onSelect = vi.fn();
    render(
      <RelationshipCandidatePicker
        workspaceId="ws-1"
        objectId="obj-1"
        targetObjectId="obj-2"
        onSelect={onSelect}
      />
    );

    fireEvent.change(screen.getByPlaceholderText("Search records…"), { target: { value: "Acme" } });

    await waitFor(() => expect(screen.getByText("Acme Corp")).toBeInTheDocument(), { timeout: 1000 });
    fireEvent.click(screen.getByText("Acme Corp"));

    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ record_id: "r1", record_label: "Acme Corp" })
    );
    // The picker clears its own search after a selection -- it never keeps
    // a "selected" list of its own.
    expect((screen.getByPlaceholderText("Search records…") as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/not saved/i)).toBeInTheDocument();
  }, 2000);

  it("shows a loading state while searching", () => {
    useRelationshipCandidatesMock.mockReturnValue({
      items: [], total: 0, limit: 20, offset: 0, isLoading: true, error: null,
    });
    render(
      <RelationshipCandidatePicker workspaceId="ws-1" objectId="obj-1" targetObjectId="obj-2" onSelect={vi.fn()} />
    );
    fireEvent.change(screen.getByPlaceholderText("Search records…"), { target: { value: "x" } });
    expect(screen.getByText("Searching…")).toBeInTheDocument();
  });

  it("shows an empty state when nothing matches", () => {
    useRelationshipCandidatesMock.mockReturnValue({
      items: [], total: 0, limit: 20, offset: 0, isLoading: false, error: null,
    });
    render(
      <RelationshipCandidatePicker workspaceId="ws-1" objectId="obj-1" targetObjectId="obj-2" onSelect={vi.fn()} />
    );
    fireEvent.change(screen.getByPlaceholderText("Search records…"), { target: { value: "nomatch" } });
    expect(screen.getByText("No matching records")).toBeInTheDocument();
  });

  it("shows an error state when the search fails", () => {
    useRelationshipCandidatesMock.mockReturnValue({
      items: [], total: 0, limit: 20, offset: 0, isLoading: false, error: new Error("boom"),
    });
    render(
      <RelationshipCandidatePicker workspaceId="ws-1" objectId="obj-1" targetObjectId="obj-2" onSelect={vi.fn()} />
    );
    fireEvent.change(screen.getByPlaceholderText("Search records…"), { target: { value: "x" } });
    expect(screen.getByText("Search failed.")).toBeInTheDocument();
  });
});
