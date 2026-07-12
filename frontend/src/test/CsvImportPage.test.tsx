/**
 * Focused coverage for the CSV import pre-persistence workflow page:
 * upload -> preflight/mapping -> dry-run -> truthful summary rendering,
 * rejection-CSV visibility, and the "execution unavailable" messaging.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CsvImportPage from "@/app/(app)/crm/[objectSlug]/import/page";
import {
  CsvImportSchemaResponse,
  CsvImportPreflightResult,
  CsvImportDryRunPolicyResult,
} from "@/lib/api";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ objectSlug: "contacts" }),
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/hooks/useWorkspace", () => ({
  useWorkspace: () => ({ currentWorkspace: { id: "ws-1" } }),
}));

vi.mock("@/hooks/useCRM", () => ({
  useCRMObjects: () => ({
    objects: [{ id: "contact-obj", slug: "contacts", name: "Contact", plural_name: "Contacts" }],
  }),
}));

const schemaMock = vi.fn();
const preflightMock = vi.fn();
const dryRunMock = vi.fn();
const rejectionCsvMock = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    csvImportApi: {
      schema: (...args: unknown[]) => schemaMock(...args),
      preflight: (...args: unknown[]) => preflightMock(...args),
      dryRun: (...args: unknown[]) => dryRunMock(...args),
      rejectionCsv: (...args: unknown[]) => rejectionCsvMock(...args),
    },
  };
});

const schemaResponse: CsvImportSchemaResponse = {
  attributes: [
    { id: "name-attr", display_name: "Name", slug: "name", attribute_type: "text", importable: true, is_required: true, config: {} },
    { id: "email-attr", display_name: "Email", slug: "email", attribute_type: "email", importable: true, is_required: false, config: {} },
  ],
};

const preflightResponse: CsvImportPreflightResult = {
  filename: "contacts.csv",
  encoding: "utf-8",
  original_headers: ["name", "email"],
  normalized_headers: ["name", "email"],
  total_data_row_count: 2,
  preview_rows: [],
  preview_truncated: false,
  mapping_suggestions: [
    { source_header: "name", source_column_number: 1, target_attribute_id: "name-attr", target_display_name: "Name", match_reason: "display_name_exact" },
    { source_header: "email", source_column_number: 2, target_attribute_id: "email-attr", target_display_name: "Email", match_reason: "display_name_exact" },
  ],
  validated_mapping: [],
  errors: [],
  warnings: [],
  eligible_to_proceed: true,
};

function makeDryRunResult(overrides: Partial<CsvImportDryRunPolicyResult> = {}): CsvImportDryRunPolicyResult {
  return {
    filename: "contacts.csv",
    dry_run_completed: true,
    file_errors: [],
    file_warnings: [],
    policies: { invalid_row_policy: "all_or_nothing", unique_match_attribute_id: "email-attr", duplicate_action: "skip" },
    summary: {
      total_logical_data_rows: 2,
      valid_row_count: 1,
      invalid_row_count: 1,
      duplicate_match_count: 0,
      create_candidate_count: 1,
      update_candidate_count: 0,
      skipped_row_count: 0,
      execution_blocked: true,
      execution_blocked_reason: "The all_or_nothing policy blocks execution while any invalid row exists.",
    },
    rows: [
      { source_row_number: 2, status: "create", reason_codes: [], remediation: [], source_values: { name: "Ada", email: "ada@example.com" }, proposed_values: { name: "Ada", email: "ada@example.com" }, matched_existing: false },
      { source_row_number: 3, status: "invalid", reason_codes: ["MISSING_MAPPED_SOURCE_COLUMN"], remediation: ["Mapping references a source column that is missing or ambiguous."], source_values: {}, proposed_values: {}, matched_existing: false },
    ],
    ...overrides,
  };
}

function makeFile(): File {
  return new File(["name,email\nAda,ada@example.com\n"], "contacts.csv", { type: "text/csv" });
}

beforeEach(() => {
  pushMock.mockReset();
  schemaMock.mockReset();
  preflightMock.mockReset();
  dryRunMock.mockReset();
  rejectionCsvMock.mockReset();
  schemaMock.mockResolvedValue(schemaResponse);
  preflightMock.mockResolvedValue(preflightResponse);
});

async function uploadAndAnalyze() {
  render(<CsvImportPage />);
  const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(fileInput, { target: { files: [makeFile()] } });
  fireEvent.click(screen.getByText("Analyze CSV"));
  await waitFor(() => expect(screen.getByText("Map columns")).toBeInTheDocument());
}

describe("CsvImportPage", () => {
  it("always shows the preview-only banner and a disabled execution control", async () => {
    render(<CsvImportPage />);
    expect(screen.getByText(/preview-only workflow/i)).toBeInTheDocument();
    const executeButton = screen.getByText(/Import records/i);
    expect(executeButton).toBeDisabled();
  });

  it("uploads a file and transitions to the mapping step with pre-filled suggestions", async () => {
    await uploadAndAnalyze();
    expect(preflightMock).toHaveBeenCalledWith("ws-1", "contact-obj", expect.any(File));
    expect(screen.getByText("2 data rows found.", { exact: false })).toBeInTheDocument();
  });

  it("requires a unique match attribute before the dry-run button is enabled", async () => {
    await uploadAndAnalyze();
    const runButton = screen.getByText("Run dry run");
    expect(runButton).toBeDisabled();
  });

  it("runs the dry run with the selected mapping and policies", async () => {
    dryRunMock.mockResolvedValue(makeDryRunResult());
    await uploadAndAnalyze();

    const selects = screen.getAllByRole("combobox");
    const matchSelect = selects[selects.length - 1];
    fireEvent.change(matchSelect, { target: { value: "email-attr" } });

    fireEvent.click(screen.getByText("Run dry run"));
    await waitFor(() => expect(dryRunMock).toHaveBeenCalled());

    const [, , , mapping, policies] = dryRunMock.mock.calls[0];
    expect(mapping).toEqual(
      expect.arrayContaining([
        { source_header: "name", target_attribute_id: "name-attr" },
        { source_header: "email", target_attribute_id: "email-attr" },
      ])
    );
    expect(policies).toEqual({
      invalid_row_policy: "all_or_nothing",
      unique_match_attribute_id: "email-attr",
      duplicate_action: "skip",
    });
  });

  it("renders every summary category truthfully from server-derived counts", async () => {
    dryRunMock.mockResolvedValue(makeDryRunResult());
    await uploadAndAnalyze();
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[selects.length - 1], { target: { value: "email-attr" } });
    fireEvent.click(screen.getByText("Run dry run"));
    await waitFor(() => expect(screen.getByText("Total rows")).toBeInTheDocument());

    expect(screen.getByText("Valid")).toBeInTheDocument();
    // "Invalid" appears twice: the summary card label and the row status
    // badge -- both are expected, so assert on the count instead of a
    // single unambiguous match.
    expect(screen.getAllByText("Invalid").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Duplicate matches")).toBeInTheDocument();
    expect(screen.getByText("Create candidates")).toBeInTheDocument();
    expect(screen.getByText("Update candidates")).toBeInTheDocument();
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    // Row-level distinctions.
    expect(screen.getByText("Create candidate")).toBeInTheDocument();
  });

  it("communicates that execution remains unavailable even after a completed dry run", async () => {
    dryRunMock.mockResolvedValue(makeDryRunResult());
    await uploadAndAnalyze();
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[selects.length - 1], { target: { value: "email-attr" } });
    fireEvent.click(screen.getByText("Run dry run"));
    await waitFor(() => expect(screen.getByText("Total rows")).toBeInTheDocument());

    expect(screen.getByText(/Record execution itself is not available in this phase/i)).toBeInTheDocument();
    expect(screen.getByText(/Import records/i)).toBeDisabled();
  });

  it("shows the rejection CSV download only when there are invalid rows", async () => {
    dryRunMock.mockResolvedValue(makeDryRunResult());
    await uploadAndAnalyze();
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[selects.length - 1], { target: { value: "email-attr" } });
    fireEvent.click(screen.getByText("Run dry run"));
    await waitFor(() => expect(screen.getByText("Download rejected rows CSV")).toBeInTheDocument());
  });

  it("hides the rejection CSV download when there are no invalid rows", async () => {
    dryRunMock.mockResolvedValue(makeDryRunResult({
      summary: {
        total_logical_data_rows: 1, valid_row_count: 1, invalid_row_count: 0,
        duplicate_match_count: 0, create_candidate_count: 1, update_candidate_count: 0,
        skipped_row_count: 0, execution_blocked: false, execution_blocked_reason: null,
      },
      rows: [{ source_row_number: 2, status: "create", reason_codes: [], remediation: [], source_values: {}, proposed_values: {}, matched_existing: false }],
    }));
    await uploadAndAnalyze();
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[selects.length - 1], { target: { value: "email-attr" } });
    fireEvent.click(screen.getByText("Run dry run"));
    await waitFor(() => expect(screen.getByText("Total rows")).toBeInTheDocument());
    expect(screen.queryByText("Download rejected rows CSV")).not.toBeInTheDocument();
  });

  it("does not claim CRM records were imported anywhere in the completed result", async () => {
    dryRunMock.mockResolvedValue(makeDryRunResult());
    await uploadAndAnalyze();
    const selects = screen.getAllByRole("combobox");
    fireEvent.change(selects[selects.length - 1], { target: { value: "email-attr" } });
    fireEvent.click(screen.getByText("Run dry run"));
    await waitFor(() => expect(screen.getByText("Total rows")).toBeInTheDocument());

    expect(screen.queryByText(/import(ed|ing)? successfully/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/records? created/i)).not.toBeInTheDocument();
  });

  it("surfaces file-level preflight errors and does not advance to mapping", async () => {
    preflightMock.mockResolvedValue({ ...preflightResponse, errors: [{ code: "INVALID_ENCODING", message: "CSV must be encoded as UTF-8 or UTF-8 with a BOM.", row_number: null, column_number: null, source_header: null, target_attribute_id: null, context: {} }] });
    render(<CsvImportPage />);
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [makeFile()] } });
    fireEvent.click(screen.getByText("Analyze CSV"));
    await waitFor(() => expect(screen.getByText(/must be encoded as UTF-8/i)).toBeInTheDocument());
    expect(screen.queryByText("Map columns")).not.toBeInTheDocument();
  });
});
