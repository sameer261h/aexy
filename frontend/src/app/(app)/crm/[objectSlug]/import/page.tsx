"use client";

import { useCallback, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useWorkspace } from "@/hooks/useWorkspace";
import { useCRMObjects } from "@/hooks/useCRM";
import {
  csvImportApi,
  CsvColumnMapping,
  CsvDuplicateAction,
  CsvFullTargetAttribute,
  CsvImportDryRunPolicyResult,
  CsvImportPreflightResult,
  CsvInvalidRowPolicy,
  CsvPreflightIssue,
} from "@/lib/api";

type WizardStep = "upload" | "mapping" | "results";

function issueLine(issue: CsvPreflightIssue): string {
  const location = issue.row_number != null ? `Row ${issue.row_number}` : issue.source_header || "File";
  return `${location}: ${issue.message}`;
}

const STATUS_LABEL: Record<string, string> = {
  create: "Create candidate",
  update: "Update candidate",
  skipped_duplicate: "Skipped (duplicate)",
  invalid: "Invalid",
};

const STATUS_COLOR: Record<string, string> = {
  create: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  update: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  skipped_duplicate: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  invalid: "bg-red-500/15 text-red-400 border-red-500/30",
};

export default function CsvImportPage() {
  const params = useParams();
  const router = useRouter();
  const objectSlug = params.objectSlug as string;
  const { currentWorkspace } = useWorkspace();
  const workspaceId = currentWorkspace?.id || null;
  const { objects } = useCRMObjects(workspaceId);
  const currentObject = objects.find((o) => o.slug === objectSlug);

  const [step, setStep] = useState<WizardStep>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [targets, setTargets] = useState<CsvFullTargetAttribute[]>([]);
  const [preflight, setPreflight] = useState<CsvImportPreflightResult | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [invalidRowPolicy, setInvalidRowPolicy] = useState<CsvInvalidRowPolicy>("all_or_nothing");
  const [uniqueMatchAttributeId, setUniqueMatchAttributeId] = useState("");
  const [duplicateAction, setDuplicateAction] = useState<CsvDuplicateAction>("skip");
  const [dryRunResult, setDryRunResult] = useState<CsvImportDryRunPolicyResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const mappingList = useMemo<CsvColumnMapping[]>(
    () =>
      Object.entries(mapping)
        .filter(([, targetId]) => targetId)
        .map(([source_header, target_attribute_id]) => ({ source_header, target_attribute_id })),
    [mapping]
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFile(e.target.files?.[0] || null);
    setError(null);
  };

  const handleAnalyze = async () => {
    if (!file || !workspaceId || !currentObject) return;
    setIsLoading(true);
    setError(null);
    try {
      const [schemaResp, preflightResp] = await Promise.all([
        csvImportApi.schema(workspaceId, currentObject.id),
        csvImportApi.preflight(workspaceId, currentObject.id, file),
      ]);
      setTargets(schemaResp.attributes);
      setPreflight(preflightResp);
      const initialMapping: Record<string, string> = {};
      for (const suggestion of preflightResp.mapping_suggestions) {
        initialMapping[suggestion.source_header] = suggestion.target_attribute_id;
      }
      setMapping(initialMapping);
      setStep("mapping");
    } catch {
      setError("Couldn't analyze this CSV. Confirm it's a valid file and try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleRunDryRun = async () => {
    if (!file || !workspaceId || !currentObject || !uniqueMatchAttributeId) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await csvImportApi.dryRun(workspaceId, currentObject.id, file, mappingList, {
        invalid_row_policy: invalidRowPolicy,
        unique_match_attribute_id: uniqueMatchAttributeId,
        duplicate_action: duplicateAction,
      });
      setDryRunResult(result);
      setStep("results");
    } catch {
      setError("Dry run failed. Check your mapping and policy selections.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleDownloadRejected = useCallback(async () => {
    if (!file || !workspaceId || !currentObject || !uniqueMatchAttributeId) return;
    const blob = await csvImportApi.rejectionCsv(workspaceId, currentObject.id, file, mappingList, {
      invalid_row_policy: invalidRowPolicy,
      unique_match_attribute_id: uniqueMatchAttributeId,
      duplicate_action: duplicateAction,
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "rejected_rows.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, [file, workspaceId, currentObject, mappingList, invalidRowPolicy, uniqueMatchAttributeId, duplicateAction]);

  const requiredUnmapped = targets.filter(
    (t) => t.is_required && !mappingList.some((m) => m.target_attribute_id === t.id)
  );

  if (!currentObject) {
    return <div className="p-8 text-sm text-muted-foreground">Loading object…</div>;
  }

  return (
    <div className="min-h-screen bg-background p-8 max-w-4xl mx-auto">
      <button
        onClick={() => router.push(`/crm/${objectSlug}`)}
        className="text-sm text-muted-foreground hover:text-foreground mb-4"
      >
        &larr; Back to {currentObject.plural_name}
      </button>

      <h1 className="text-xl font-bold text-foreground mb-1">Import CSV into {currentObject.plural_name}</h1>

      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 my-4 text-sm text-amber-300">
        This is a preview-only workflow. No {currentObject.plural_name.toLowerCase()} records are created,
        updated, or deleted here — record creation is a later phase, not available yet.
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 mb-4 text-sm text-red-400">
          {error}
        </div>
      )}

      {step === "upload" && (
        <div className="space-y-4">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={handleFileChange}
            className="block w-full text-sm text-foreground file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-purple-600 file:text-white hover:file:bg-purple-700"
          />
          <button
            onClick={handleAnalyze}
            disabled={!file || isLoading}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm"
          >
            {isLoading ? "Analyzing…" : "Analyze CSV"}
          </button>
        </div>
      )}

      {step === "mapping" && preflight && (
        <div className="space-y-6">
          <div>
            <h2 className="text-sm font-semibold text-foreground mb-2">Preflight summary</h2>
            <p className="text-sm text-muted-foreground">
              {preflight.total_data_row_count} data row{preflight.total_data_row_count === 1 ? "" : "s"} found.
              Encoding: {preflight.encoding}.
            </p>
            {preflight.errors.length > 0 && (
              <ul className="mt-2 text-sm text-red-400 list-disc list-inside">
                {preflight.errors.map((issue, idx) => (
                  <li key={idx}>{issueLine(issue)}</li>
                ))}
              </ul>
            )}
            {preflight.warnings.length > 0 && (
              <ul className="mt-2 text-sm text-amber-400 list-disc list-inside">
                {preflight.warnings.map((issue, idx) => (
                  <li key={idx}>{issueLine(issue)}</li>
                ))}
              </ul>
            )}
          </div>

          {preflight.errors.length === 0 && (
            <>
              <div>
                <h2 className="text-sm font-semibold text-foreground mb-2">Map columns</h2>
                <div className="space-y-2">
                  {preflight.original_headers.map((header) => (
                    <div key={header} className="flex items-center gap-3">
                      <span className="w-40 text-sm text-foreground truncate" title={header}>{header}</span>
                      <span className="text-muted-foreground">&rarr;</span>
                      <select
                        value={mapping[header] || ""}
                        onChange={(e) => setMapping((prev) => ({ ...prev, [header]: e.target.value }))}
                        className="flex-1 text-sm bg-muted border border-border rounded-md px-2 py-1.5 text-foreground"
                      >
                        <option value="">— Ignore this column —</option>
                        {targets.map((t) => (
                          <option key={t.id} value={t.id}>
                            {t.display_name}{t.is_required ? " (required)" : ""}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
                {requiredUnmapped.length > 0 && (
                  <p className="text-sm text-red-400 mt-2">
                    Missing required mapping: {requiredUnmapped.map((t) => t.display_name).join(", ")}
                  </p>
                )}
              </div>

              <div>
                <h2 className="text-sm font-semibold text-foreground mb-2">Invalid-row policy</h2>
                <div className="flex gap-4 text-sm text-foreground">
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      checked={invalidRowPolicy === "all_or_nothing"}
                      onChange={() => setInvalidRowPolicy("all_or_nothing")}
                    />
                    All or nothing (default)
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      checked={invalidRowPolicy === "partial"}
                      onChange={() => setInvalidRowPolicy("partial")}
                    />
                    Partial (execute valid rows only)
                  </label>
                </div>
              </div>

              <div>
                <h2 className="text-sm font-semibold text-foreground mb-2">Duplicate matching</h2>
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-sm text-muted-foreground">Match existing records by:</span>
                  <select
                    value={uniqueMatchAttributeId}
                    onChange={(e) => setUniqueMatchAttributeId(e.target.value)}
                    className="text-sm bg-muted border border-border rounded-md px-2 py-1.5 text-foreground"
                  >
                    <option value="">— Select an attribute —</option>
                    {targets
                      .filter((t) => mappingList.some((m) => m.target_attribute_id === t.id))
                      .map((t) => (
                        <option key={t.id} value={t.id}>{t.display_name}</option>
                      ))}
                  </select>
                </div>
                <div className="flex gap-4 text-sm text-foreground">
                  {(["skip", "update_existing", "create_anyway"] as const).map((action) => (
                    <label key={action} className="flex items-center gap-2">
                      <input
                        type="radio"
                        checked={duplicateAction === action}
                        onChange={() => setDuplicateAction(action)}
                      />
                      {action === "skip" && "Skip duplicates"}
                      {action === "update_existing" && "Update existing"}
                      {action === "create_anyway" && "Create anyway"}
                    </label>
                  ))}
                </div>
              </div>

              <button
                onClick={handleRunDryRun}
                disabled={isLoading || !uniqueMatchAttributeId || requiredUnmapped.length > 0}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm"
              >
                {isLoading ? "Running dry run…" : "Run dry run"}
              </button>
            </>
          )}
        </div>
      )}

      {step === "results" && dryRunResult && (
        <div className="space-y-6">
          {!dryRunResult.dry_run_completed && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-3 text-sm text-red-400">
              <p className="font-medium mb-1">Dry run could not complete.</p>
              <ul className="list-disc list-inside">
                {dryRunResult.file_errors.map((issue, idx) => (
                  <li key={idx}>{issueLine(issue)}</li>
                ))}
              </ul>
            </div>
          )}

          {dryRunResult.dry_run_completed && (
            <>
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
                {[
                  ["Total rows", dryRunResult.summary.total_logical_data_rows],
                  ["Valid", dryRunResult.summary.valid_row_count],
                  ["Invalid", dryRunResult.summary.invalid_row_count],
                  ["Duplicate matches", dryRunResult.summary.duplicate_match_count],
                  ["Create candidates", dryRunResult.summary.create_candidate_count],
                  ["Update candidates", dryRunResult.summary.update_candidate_count],
                  ["Skipped", dryRunResult.summary.skipped_row_count],
                ].map(([label, value]) => (
                  <div key={label as string} className="bg-muted/50 border border-border rounded-xl p-3">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="text-lg font-semibold text-foreground">{value}</p>
                  </div>
                ))}
              </div>

              <div
                className={`rounded-lg border px-4 py-3 text-sm ${
                  dryRunResult.summary.execution_blocked
                    ? "border-red-500/30 bg-red-500/5 text-red-400"
                    : "border-emerald-500/30 bg-emerald-500/5 text-emerald-400"
                }`}
              >
                {dryRunResult.summary.execution_blocked
                  ? `Execution would remain blocked: ${dryRunResult.summary.execution_blocked_reason || "invalid rows present"}.`
                  : "Execution would not be blocked by row validity under the selected policy."}
                {" "}Record execution itself is not available in this phase.
              </div>

              {dryRunResult.summary.invalid_row_count > 0 && (
                <button
                  onClick={handleDownloadRejected}
                  className="px-4 py-2 border border-border hover:bg-accent text-foreground rounded-lg text-sm"
                >
                  Download rejected rows CSV
                </button>
              )}

              <div className="border border-border rounded-lg overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-muted-foreground">
                    <tr>
                      <th className="text-left px-3 py-2">Row</th>
                      <th className="text-left px-3 py-2">Status</th>
                      <th className="text-left px-3 py-2">Diagnostics</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dryRunResult.rows.map((row) => (
                      <tr key={row.source_row_number} className="border-t border-border">
                        <td className="px-3 py-2 text-foreground">{row.source_row_number}</td>
                        <td className="px-3 py-2">
                          <span className={`inline-flex px-2 py-0.5 rounded-full text-xs border ${STATUS_COLOR[row.status]}`}>
                            {STATUS_LABEL[row.status]}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {row.remediation.length > 0 ? row.remediation.join("; ") : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <button
            onClick={() => setStep("mapping")}
            className="px-4 py-2 border border-border hover:bg-accent text-foreground rounded-lg text-sm"
          >
            Back to mapping
          </button>
        </div>
      )}

      <div className="mt-10 pt-6 border-t border-border">
        <button
          disabled
          title="Record execution belongs to a later phase and is not available yet."
          className="px-4 py-2 bg-muted text-muted-foreground rounded-lg text-sm cursor-not-allowed opacity-60"
        >
          Import records (not available yet)
        </button>
      </div>
    </div>
  );
}
