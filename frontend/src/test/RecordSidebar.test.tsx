/**
 * Focused coverage proving RecordSidebar's field-value rendering split:
 * record_reference attributes now go through RelationshipFieldValue
 * (resolved labels, never raw IDs); every other attribute type is
 * completely untouched, still rendered via the shared FieldRenderer.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { RecordSidebar } from "@/components/crm/RecordSidebar";
import { CRMAttribute, CRMObject, CRMRecord, RelationshipGroup } from "@/lib/api";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

const fieldRendererMock = vi.fn((_props: unknown) => <span data-testid="field-renderer-output" />);
vi.mock("@/components/fields", () => ({
  FieldRenderer: (props: unknown) => fieldRendererMock(props),
  FieldEditor: () => null,
}));

const textAttr = {
  id: "attr-text", slug: "name", name: "Name", attribute_type: "text",
  is_system: false,
} as CRMAttribute;

const referenceAttr = {
  id: "attr-ref", slug: "primary_company", name: "Primary Company",
  attribute_type: "record_reference", is_system: false,
} as CRMAttribute;

const record = {
  id: "rec-1", workspace_id: "ws-1", object_id: "contact-obj",
  values: { name: "Alice", primary_company: "company-id-1" },
  display_name: "Alice", owner_id: null, created_by_id: null,
  is_archived: false, archived_at: null, created_at: "2026-01-01", updated_at: "2026-01-01",
} as CRMRecord;

const objects: CRMObject[] = [{ id: "company-obj", slug: "companies" } as CRMObject];

const groups: RelationshipGroup[] = [{
  attribute_id: "attr-ref", attribute_name: "Primary Company",
  target_object_id: "company-obj", allow_multiple: false, total: 1,
  items: [{
    attribute_id: "attr-ref", record_id: "company-id-1", accessible: true,
    object_id: "company-obj", object_label: "Company", record_label: "Acme Corp", is_archived: false,
  }],
}];

describe("RecordSidebar field rendering", () => {
  it("renders a record_reference attribute via RelationshipFieldValue, not FieldRenderer", () => {
    fieldRendererMock.mockClear();
    render(
      <RecordSidebar
        record={record}
        attributes={[referenceAttr]}
        relationshipGroups={groups}
        objects={objects}
      />
    );
    expect(screen.getByText("Acme Corp")).toBeInTheDocument();
    expect(screen.queryByText("company-id-1")).not.toBeInTheDocument();
    expect(fieldRendererMock).not.toHaveBeenCalled();
  });

  it("still renders non-reference attributes via the shared FieldRenderer, unchanged", () => {
    fieldRendererMock.mockClear();
    render(<RecordSidebar record={record} attributes={[textAttr]} />);
    expect(fieldRendererMock).toHaveBeenCalledWith(
      expect.objectContaining({ attribute: textAttr, value: "Alice", surface: "detail_view" })
    );
  });
});
