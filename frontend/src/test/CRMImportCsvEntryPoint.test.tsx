/**
 * Coverage for Thread 1: the CRM object grid page (shared by People,
 * Companies, and Deals via /crm/[objectSlug]) must show an "Import CSV"
 * action and hand the import flow the object the page is already showing
 * — never a generic/implicit object selection.
 *
 * Heavy child components (table/board/filter/etc.) are stubbed so this test
 * is only exercising the page's own wiring, not their internals.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";

let currentSlug = "people";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ objectSlug: currentSlug }),
}));

const OBJECTS_BY_SLUG: Record<string, { id: string; slug: string; name: string; plural_name: string; object_type: string; attributes: unknown[] }> = {
  people: { id: "obj-person", slug: "people", name: "Person", plural_name: "People", object_type: "person", attributes: [] },
  companies: { id: "obj-company", slug: "companies", name: "Company", plural_name: "Companies", object_type: "company", attributes: [] },
  deals: { id: "obj-deal", slug: "deals", name: "Deal", plural_name: "Deals", object_type: "deal", attributes: [] },
};

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({ currentWorkspace: { id: "ws-1" } }),
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { id: "u1" }, logout: vi.fn() }),
}));
vi.mock("@/hooks/useCRM", () => ({
  useCRMObjects: () => ({ objects: Object.values(OBJECTS_BY_SLUG) }),
  useCRMRecords: () => ({
    records: [],
    total: 0,
    isLoading: false,
    createRecord: vi.fn(),
    updateRecord: vi.fn(),
    deleteRecord: vi.fn(),
    bulkDeleteRecords: vi.fn(),
    isCreating: false,
    isDeleting: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/hooks/useTables", () => ({
  useSavedViews: () => ({
    views: [],
    createView: vi.fn(),
    updateView: vi.fn(),
    deleteView: vi.fn(),
    isCreating: false,
    isUpdating: false,
  }),
}));

vi.mock("@/components/ui/search-input", () => ({ SearchInput: () => <div /> }));
vi.mock("@/components/crm/ViewSwitcher", () => ({ ViewSwitcher: () => <div /> }));
vi.mock("@/components/crm/SavedViewSwitcher", () => ({ SavedViewSwitcher: () => <div /> }));
vi.mock("@/components/crm/DataTable", () => ({ DataTable: () => <div data-testid="data-table" /> }));
vi.mock("@/components/crm/KanbanBoard", () => ({ KanbanBoard: () => <div /> }));
vi.mock("@/components/crm/PipelineBoard", () => ({ PipelineBoard: () => <div /> }));
vi.mock("@/components/crm/ColumnSelector", () => ({ ColumnVisibilityMenu: () => <div /> }));
vi.mock("@/components/fields", () => ({ FieldEditor: () => <div /> }));
vi.mock("@/components/tables", () => ({ TableFilterPanel: () => <div />, FilterRule: {} }));

const importModalSpy = vi.fn();
vi.mock("@/components/crm/ImportCsvModal", () => ({
  ImportCsvModal: (props: { isOpen: boolean; object: { slug: string; id: string } }) => {
    importModalSpy(props.isOpen, props.object?.slug, props.object?.id);
    return props.isOpen ? <div data-testid="import-modal">{props.object?.slug}</div> : null;
  },
}));

import RecordsPage from "@/app/(app)/crm/[objectSlug]/page";

beforeEach(() => {
  importModalSpy.mockClear();
});

describe.each([
  ["people", "obj-person"],
  ["companies", "obj-company"],
  ["deals", "obj-deal"],
])("CRM grid Import CSV entry point (/crm/%s)", (slug, expectedObjectId) => {
  it("shows an Import CSV button and supplies the current page's object, not a generic picker", () => {
    currentSlug = slug;
    render(<RecordsPage />);

    const button = screen.getByText("Import CSV");
    expect(button).toBeInTheDocument();

    fireEvent.click(button);

    expect(importModalSpy).toHaveBeenLastCalledWith(true, slug, expectedObjectId);
  });
});
