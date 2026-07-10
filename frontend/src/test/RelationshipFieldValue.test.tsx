/**
 * Focused coverage for RelationshipFieldValue -- the record_reference
 * counterpart to FieldRenderer used on non-Related-tab record-detail
 * surfaces (sidebar, highlights). Purely presentational: driven entirely by
 * an already-loaded `groups` prop, never fetches on its own.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RelationshipFieldValue } from "@/components/crm/relationships/RelationshipFieldValue";
import { CRMAttribute, CRMObject, RelationshipGroup, RelatedRecordSummary } from "@/lib/api";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const singleAttr = {
  id: "attr-single", slug: "primary_company", name: "Primary Company",
  attribute_type: "record_reference",
} as CRMAttribute;

const multiAttr = {
  id: "attr-multi", slug: "companies", name: "Companies",
  attribute_type: "record_reference",
} as CRMAttribute;

const objects: CRMObject[] = [
  { id: "company-obj", slug: "companies" } as CRMObject,
  { id: "person-obj", slug: "people" } as CRMObject,
];

function item(overrides: Partial<RelatedRecordSummary>): RelatedRecordSummary {
  return {
    attribute_id: "attr-single", record_id: "rec-1", accessible: true,
    object_id: "company-obj", object_label: "Company", record_label: "Acme Corp",
    is_archived: false,
    ...overrides,
  };
}

function group(overrides: Partial<RelationshipGroup>): RelationshipGroup {
  return {
    attribute_id: "attr-single", attribute_name: "Primary Company",
    target_object_id: "company-obj", allow_multiple: false, total: 0, items: [],
    ...overrides,
  };
}

beforeEach(() => pushMock.mockReset());

describe("RelationshipFieldValue", () => {
  it("renders a label instead of a UUID for a single relationship", () => {
    render(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({ items: [item({})], total: 1 })]}
      />
    );
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.queryByText("rec-1")).not.toBeInTheDocument();
  });

  it("renders multi-relationship labels in stored order", () => {
    render(
      <RelationshipFieldValue
        attribute={multiAttr}
        objects={objects}
        groups={[group({
          attribute_id: "attr-multi", allow_multiple: true,
          items: [
            item({ attribute_id: "attr-multi", record_id: "rec-b", record_label: "Beta Inc" }),
            item({ attribute_id: "attr-multi", record_id: "rec-a", record_label: "Acme Corp" }),
          ],
          total: 2,
        })]}
      />
    );
    const labels = screen.getAllByText(/Beta Inc|Acme Corp/).map((el) => el.textContent);
    expect(labels).toEqual(["Beta Inc", "Acme Corp"]);
  });

  it("links an authorized relationship value to the correct record-detail route", () => {
    render(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({ items: [item({})], total: 1 })]}
      />
    );
    fireEvent.click(screen.getByText("Acme Corp"));
    expect(pushMock).toHaveBeenCalledWith("/crm/companies/rec-1");
  });

  it("renders the safe opaque placeholder for a stale relationship ID", () => {
    render(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({
          items: [item({ record_id: "stale-1", accessible: false, object_id: null, object_label: null, record_label: null, is_archived: null })],
          total: 1,
        })]}
      />
    );
    expect(screen.getByText("Unavailable reference")).toBeInTheDocument();
    expect(screen.queryByText("stale-1")).not.toBeInTheDocument();
  });

  it("renders the safe opaque placeholder for an inaccessible relationship ID", () => {
    render(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({
          items: [item({ record_id: "forbidden-1", accessible: false, object_id: null, object_label: null, record_label: null, is_archived: null })],
          total: 1,
        })]}
      />
    );
    expect(screen.getByText("Unavailable reference")).toBeInTheDocument();
  });

  it("does not create a link for unresolved values", () => {
    render(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({
          items: [item({ record_id: "stale-1", accessible: false, object_id: null, object_label: null, record_label: null, is_archived: null })],
          total: 1,
        })]}
      />
    );
    fireEvent.click(screen.getByText("Unavailable reference"));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("renders the established empty state when the relationship has no value", () => {
    render(<RelationshipFieldValue attribute={singleAttr} objects={objects} groups={[group({})]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders the highlights-surface empty state when surface is 'highlights'", () => {
    render(<RelationshipFieldValue attribute={singleAttr} objects={objects} groups={[]} surface="highlights" />);
    expect(screen.getByText("Not set")).toBeInTheDocument();
  });

  it("does not retain the previous record's label after switching source records", () => {
    const { rerender } = render(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({ items: [item({ record_label: "Old Record's Company" })], total: 1 })]}
      />
    );
    expect(screen.getByText("Old Record's Company")).toBeInTheDocument();

    // Simulates navigating to a different source record: react-query resets
    // to an empty result for the new query key before the new data loads.
    rerender(<RelationshipFieldValue attribute={singleAttr} objects={objects} groups={[]} />);
    expect(screen.queryByText("Old Record's Company")).not.toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("does not reuse summaries from a different target object", () => {
    const { rerender } = render(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({ target_object_id: "company-obj", items: [item({})], total: 1 })]}
      />
    );
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();

    rerender(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({
          target_object_id: "person-obj",
          items: [item({ record_id: "rec-2", object_id: "person-obj", object_label: "Person", record_label: "Jane Doe" })],
          total: 1,
        })]}
      />
    );
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.queryByText("Acme Corp")).not.toBeInTheDocument();
  });

  it("reflects an updated group after a successful mutation (simulated refetch)", () => {
    const { rerender } = render(
      <RelationshipFieldValue attribute={singleAttr} objects={objects} groups={[group({})]} />
    );
    expect(screen.getByText("—")).toBeInTheDocument();

    // Mutation succeeded -- the shared relationships query was invalidated
    // and refetched, producing a group with the newly-saved value.
    rerender(
      <RelationshipFieldValue
        attribute={singleAttr}
        objects={objects}
        groups={[group({ items: [item({})], total: 1 })]}
      />
    );
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
  });

  it("keeps the previously rendered value when a mutation fails (groups prop unchanged)", () => {
    const groups = [group({ items: [item({})], total: 1 })];
    const { rerender } = render(
      <RelationshipFieldValue attribute={singleAttr} objects={objects} groups={groups} />
    );
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();

    // Mutation failed server-side -- no cache invalidation fires, so this
    // surface's groups prop never changes.
    rerender(<RelationshipFieldValue attribute={singleAttr} objects={objects} groups={groups} />);
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
  });
});
