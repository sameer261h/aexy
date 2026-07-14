/**
 * Coverage for the CRM grid's "Import CSV" flow: file select -> client-side
 * mapping preview -> confirm -> real import via the existing, already-tested
 * BulkImportService endpoint (crmApi.objects.importCsv). This does not
 * reimplement or call PR #4's separate preview-only dry-run engine.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { CRMObject } from "@/lib/api";

const importCsvMock = vi.fn();
const toastSuccess = vi.fn();
const toastError = vi.fn();

vi.mock("@/lib/api", () => ({
  crmApi: {
    objects: {
      importCsv: (...args: unknown[]) => importCsvMock(...args),
    },
  },
}));

vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args), error: (...args: unknown[]) => toastError(...args) },
}));

import { ImportCsvModal } from "@/components/crm/ImportCsvModal";

const PEOPLE_OBJECT = {
  id: "obj-person-1",
  workspace_id: "ws-1",
  name: "Person",
  slug: "people",
  plural_name: "People",
  description: null,
  object_type: "person",
  icon: null,
  color: null,
  is_system: true,
  is_active: true,
  primary_attribute_id: null,
  record_count: 0,
  settings: {},
  attributes: [
    { id: "a1", object_id: "obj-person-1", name: "Name", slug: "name", attribute_type: "text", description: null, is_required: true, is_unique: false, is_searchable: true, is_filterable: true, is_sortable: true, is_system: false, config: {}, default_value: null, order: 0, created_at: "", updated_at: "" },
    { id: "a2", object_id: "obj-person-1", name: "Email", slug: "email", attribute_type: "email", description: null, is_required: false, is_unique: false, is_searchable: true, is_filterable: true, is_sortable: true, is_system: false, config: {}, default_value: null, order: 1, created_at: "", updated_at: "" },
  ],
  created_at: "",
  updated_at: "",
} as unknown as CRMObject;

function makeCsvFile(content: string, name = "contacts.csv") {
  return new File([content], name, { type: "text/csv" });
}

beforeEach(() => {
  importCsvMock.mockReset();
  toastSuccess.mockReset();
  toastError.mockReset();
});

describe("ImportCsvModal", () => {
  it("targets the CRM object it was opened from — no generic object picker", () => {
    render(
      <ImportCsvModal isOpen onClose={() => {}} workspaceId="ws-1" object={PEOPLE_OBJECT} onImported={() => {}} />
    );
    expect(screen.getByText(/Import People from CSV/i)).toBeInTheDocument();
    expect(screen.queryByText(/select a destination object/i)).not.toBeInTheDocument();
  });

  it("shows a mapping preview after a file is selected, matching headers to the current object's fields", async () => {
    render(
      <ImportCsvModal isOpen onClose={() => {}} workspaceId="ws-1" object={PEOPLE_OBJECT} onImported={() => {}} />
    );

    const file = makeCsvFile("Name,Email\nAlice,alice@example.com\n");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText("Confirm import")).toBeInTheDocument());
    // Header and field name are identical in this fixture ("Name" -> "Name"),
    // so each mapped row renders the label twice — assert at least one match.
    expect(screen.getAllByText("Name").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Email").length).toBeGreaterThan(0);
  });

  it("blocks confirming when a required field's column is missing", async () => {
    render(
      <ImportCsvModal isOpen onClose={() => {}} workspaceId="ws-1" object={PEOPLE_OBJECT} onImported={() => {}} />
    );

    // No "Name" column, and Name is required on this object.
    const file = makeCsvFile("Email\nalice@example.com\n");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText(/Missing a column for required field/i)).toBeInTheDocument());
    expect(screen.getByText("Confirm import")).toBeDisabled();
  });

  it("imports into the object it was opened from and shows the created/skipped summary on success", async () => {
    importCsvMock.mockResolvedValue({
      job_id: "job-1",
      status: "completed",
      total_rows: 2,
      processed: 2,
      created: 1,
      duplicates: 1,
      invalid_emails: 0,
      skipped: 0,
      errors: 0,
      enrolled: 0,
      unmapped_headers: [],
      rows: [],
    });
    const onImported = vi.fn();

    render(
      <ImportCsvModal isOpen onClose={() => {}} workspaceId="ws-1" object={PEOPLE_OBJECT} onImported={onImported} />
    );

    const file = makeCsvFile("Name,Email\nAlice,alice@example.com\nAlice,alice@example.com\n");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText("Confirm import")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Confirm import"));

    await waitFor(() =>
      expect(importCsvMock).toHaveBeenCalledWith(
        "ws-1",
        "obj-person-1",
        expect.objectContaining({ skip_duplicates: true })
      )
    );

    await waitFor(() => expect(screen.getByText("Created: 1")).toBeInTheDocument());
    expect(screen.getByText("Duplicates skipped: 1")).toBeInTheDocument();
    expect(onImported).toHaveBeenCalled();
  });

  it("shows a clear error state when the import request fails", async () => {
    importCsvMock.mockRejectedValue({ response: { data: { detail: "CSV is missing a column for required field(s): Name" } } });

    render(
      <ImportCsvModal isOpen onClose={() => {}} workspaceId="ws-1" object={PEOPLE_OBJECT} onImported={() => {}} />
    );

    const file = makeCsvFile("Name,Email\nAlice,alice@example.com\n");
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(screen.getByText("Confirm import")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Confirm import"));

    await waitFor(() =>
      expect(screen.getByText(/CSV is missing a column for required field\(s\): Name/)).toBeInTheDocument()
    );
    expect(screen.getByText("Try again")).toBeInTheDocument();
  });
});
