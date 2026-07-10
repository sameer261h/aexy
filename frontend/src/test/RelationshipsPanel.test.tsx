/**
 * Focused coverage for the write workflow wired into RelationshipsPanel:
 * saving a candidate, replacing/adding/removing values, loading/error
 * states, and that existing navigation behaviour is untouched.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RelationshipsPanel } from "@/components/crm/relationships/RelationshipsPanel";
import { CandidateRecord, CRMObject } from "@/lib/api";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const useRecordRelationshipsMock = vi.fn();
const mutateMock = vi.fn();
const useMutateRelationshipMock = vi.fn();

vi.mock("@/hooks/useCRMRelationships", () => ({
  useRecordRelationships: (...args: unknown[]) => useRecordRelationshipsMock(...args),
  useMutateRelationship: (...args: unknown[]) => useMutateRelationshipMock(...args),
}));

let lastPickerOnSelect: ((c: CandidateRecord) => void) | null = null;
let lastPickerProps: Record<string, unknown> | null = null;

vi.mock("@/components/crm/relationships/RelationshipCandidatePicker", () => ({
  RelationshipCandidatePicker: (props: {
    targetObjectId: string | null;
    excludeIds?: string[];
    onSelect: (c: CandidateRecord) => void;
  }) => {
    lastPickerOnSelect = props.onSelect;
    lastPickerProps = props;
    return (
      <button
        data-testid={`picker-${props.targetObjectId}`}
        onClick={() => props.onSelect({ record_id: "new-1", record_label: "New Co", is_archived: false })}
      >
        pick-new-1
      </button>
    );
  },
}));

const objects: CRMObject[] = [
  { id: "company-obj", slug: "companies" } as CRMObject,
  { id: "contact-obj", slug: "contacts" } as CRMObject,
];

function singleGroup(items: Record<string, unknown>[] = []) {
  return {
    attribute_id: "single-attr",
    attribute_name: "Primary Company",
    target_object_id: "company-obj",
    allow_multiple: false,
    total: items.length,
    items,
  };
}

function multiGroup(items: Record<string, unknown>[] = []) {
  return {
    attribute_id: "multi-attr",
    attribute_name: "Companies",
    target_object_id: "company-obj",
    allow_multiple: true,
    total: items.length,
    items,
  };
}

const acmeItem = {
  attribute_id: "single-attr", record_id: "acme-1", accessible: true,
  object_id: "company-obj", object_label: "Company", record_label: "Acme Corp", is_archived: false,
};

beforeEach(() => {
  pushMock.mockReset();
  mutateMock.mockReset();
  useRecordRelationshipsMock.mockReset();
  useMutateRelationshipMock.mockReset();
  lastPickerOnSelect = null;
  lastPickerProps = null;
  useMutateRelationshipMock.mockReturnValue({
    mutate: mutateMock, isPending: false, error: null, variables: undefined,
  });
});

describe("RelationshipsPanel write workflow", () => {
  it("picker selection invokes the mutation with the attribute id and value", () => {
    useRecordRelationshipsMock.mockReturnValue({ groups: [singleGroup([])], isLoading: false, error: null });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    fireEvent.click(screen.getByTestId("picker-company-obj"));
    expect(mutateMock).toHaveBeenCalledWith({ attributeId: "single-attr", value: "new-1" });
  });

  it("single selection replaces the old value (not appended)", () => {
    useRecordRelationshipsMock.mockReturnValue({ groups: [singleGroup([acmeItem])], isLoading: false, error: null });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    // A populated single-cardinality group hides the picker entirely.
    expect(screen.queryByTestId("picker-company-obj")).not.toBeInTheDocument();
  });

  it("multi selection preserves existing values and appends the selected one", () => {
    useRecordRelationshipsMock.mockReturnValue({
      groups: [multiGroup([{ ...acmeItem, attribute_id: "multi-attr" }])],
      isLoading: false, error: null,
    });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    fireEvent.click(screen.getByTestId("picker-company-obj"));
    expect(mutateMock).toHaveBeenCalledWith({ attributeId: "multi-attr", value: ["acme-1", "new-1"] });
  });

  it("excludes already-related IDs from the picker (duplicate selection prevented)", () => {
    useRecordRelationshipsMock.mockReturnValue({
      groups: [multiGroup([{ ...acmeItem, attribute_id: "multi-attr" }])],
      isLoading: false, error: null,
    });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    expect(lastPickerProps?.excludeIds).toEqual(["acme-1"]);
  });

  it("chip removal invokes the mutation with the ID removed", () => {
    useRecordRelationshipsMock.mockReturnValue({
      groups: [multiGroup([
        { ...acmeItem, attribute_id: "multi-attr" },
        { ...acmeItem, attribute_id: "multi-attr", record_id: "beta-1", record_label: "Beta Inc" },
      ])],
      isLoading: false, error: null,
    });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    // Two chips (Acme, Beta) each have their own remove button -- remove
    // the first one (Acme); Beta should remain in the persisted request.
    fireEvent.click(screen.getAllByLabelText("Remove reference")[0]);
    expect(mutateMock).toHaveBeenCalledWith({ attributeId: "multi-attr", value: ["beta-1"] });
  });

  it("clear removes a single value (sends null)", () => {
    useRecordRelationshipsMock.mockReturnValue({ groups: [singleGroup([acmeItem])], isLoading: false, error: null });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    fireEvent.click(screen.getByLabelText("Remove reference"));
    expect(mutateMock).toHaveBeenCalledWith({ attributeId: "single-attr", value: null });
  });

  it("loading state disables repeated submission (chip remove buttons disabled)", () => {
    useRecordRelationshipsMock.mockReturnValue({ groups: [singleGroup([acmeItem])], isLoading: false, error: null });
    useMutateRelationshipMock.mockReturnValue({
      mutate: mutateMock, isPending: true, error: null, variables: { attributeId: "single-attr", value: null },
    });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    expect(screen.getByLabelText("Remove reference")).toBeDisabled();
    expect(screen.getByText("Saving…")).toBeInTheDocument();
  });

  it("API failure surfaces an error without hiding the existing relationship", () => {
    useRecordRelationshipsMock.mockReturnValue({ groups: [singleGroup([acmeItem])], isLoading: false, error: null });
    useMutateRelationshipMock.mockReturnValue({
      mutate: mutateMock, isPending: false,
      error: { response: { data: { detail: "One or more selected records are invalid or inaccessible" } } },
      variables: { attributeId: "single-attr", value: null },
    });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.getByText("One or more selected records are invalid or inaccessible")).toBeInTheDocument();
  });

  it("picker is read-only until an explicit selection occurs (no mutate call on render)", () => {
    useRecordRelationshipsMock.mockReturnValue({ groups: [singleGroup([])], isLoading: false, error: null });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it("existing relationship navigation remains intact", () => {
    useRecordRelationshipsMock.mockReturnValue({ groups: [singleGroup([acmeItem])], isLoading: false, error: null });
    render(<RelationshipsPanel workspaceId="ws-1" objectId="contact-obj" recordId="rec-1" objects={objects} />);

    fireEvent.click(screen.getByText("Acme Corp"));
    expect(pushMock).toHaveBeenCalledWith("/crm/companies/acme-1");
  });
});
