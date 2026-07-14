"use client";

import { useState } from "react";
import { toast } from "sonner";
import {
  Upload,
  FileSpreadsheet,
  CheckCircle2,
  AlertCircle,
  X,
  Loader2,
} from "lucide-react";
import { crmApi, CRMObject } from "@/lib/api";

interface ImportCsvModalProps {
  isOpen: boolean;
  onClose: () => void;
  workspaceId: string;
  object: CRMObject;
  onImported: () => void;
}

interface ImportResult {
  total_rows: number;
  created: number;
  duplicates: number;
  invalid_emails: number;
  errors: number;
  unmapped_headers: string[];
}

interface MappingPreview {
  headers: string[];
  mapped: { header: string; fieldName: string }[];
  unmapped: string[];
  missingRequired: string[];
}

// Mirrors the header-matching in BulkImportService.run_import_into_crm_object
// (normalize + match against attribute slug/name) — a best-effort client-side
// preview only. The backend remains the authority on what actually imports.
function normalize(s: string): string {
  return s.trim().toLowerCase().replace(/[ -]/g, "_");
}

function previewMapping(headerLine: string, object: CRMObject): MappingPreview {
  const headers = headerLine
    .split(",")
    .map((h) => h.trim().replace(/^"|"$/g, ""))
    .filter(Boolean);

  const bySlugOrName = new Map<string, string>();
  for (const attr of object.attributes || []) {
    bySlugOrName.set(normalize(attr.slug), attr.name);
    bySlugOrName.set(normalize(attr.name), attr.name);
  }

  const mapped: { header: string; fieldName: string }[] = [];
  const unmapped: string[] = [];
  const mappedFieldNames = new Set<string>();
  for (const h of headers) {
    const fieldName = bySlugOrName.get(normalize(h));
    if (fieldName) {
      mapped.push({ header: h, fieldName });
      mappedFieldNames.add(fieldName);
    } else {
      unmapped.push(h);
    }
  }

  const missingRequired = (object.attributes || [])
    .filter((a) => a.is_required && !mappedFieldNames.has(a.name))
    .map((a) => a.name);

  return { headers, mapped, unmapped, missingRequired };
}

export function ImportCsvModal({ isOpen, onClose, workspaceId, object, onImported }: ImportCsvModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [csvContent, setCsvContent] = useState<string>("");
  const [mapping, setMapping] = useState<MappingPreview | null>(null);
  const [stage, setStage] = useState<"select" | "preview" | "importing" | "success" | "error">("select");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const reset = () => {
    setFile(null);
    setCsvContent("");
    setMapping(null);
    setStage("select");
    setResult(null);
    setErrorMsg(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const readFileAsText = (f: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result ?? ""));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(f);
    });

  const handleFile = async (f: File) => {
    if (!f.name.toLowerCase().endsWith(".csv") && f.type !== "text/csv") {
      setErrorMsg("Please select a .csv file.");
      setStage("error");
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setErrorMsg("File is larger than the 10MB limit.");
      setStage("error");
      return;
    }
    const content = await readFileAsText(f);
    const headerLine = content.split(/\r?\n/, 1)[0] || "";
    if (!headerLine) {
      setErrorMsg("This CSV has no header row.");
      setStage("error");
      return;
    }
    setFile(f);
    setCsvContent(content);
    setMapping(previewMapping(headerLine, object));
    setStage("preview");
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  };

  const handleConfirm = async () => {
    setStage("importing");
    setErrorMsg(null);
    try {
      const res = await crmApi.objects.importCsv(workspaceId, object.id, {
        csv_content: csvContent,
        skip_duplicates: true,
      });
      setResult({
        total_rows: res.total_rows,
        created: res.created,
        duplicates: res.duplicates,
        invalid_emails: res.invalid_emails,
        errors: res.errors,
        unmapped_headers: res.unmapped_headers,
      });
      setStage("success");
      toast.success(`Imported ${res.created} of ${res.total_rows} rows into ${object.plural_name || object.name}`);
      onImported();
    } catch (e) {
      const message =
        e && typeof e === "object" && "response" in e
          ? // @ts-expect-error axios error shape
            e.response?.data?.detail
          : null;
      const finalMessage = message || (e instanceof Error ? e.message : "Failed to import this file.");
      setErrorMsg(finalMessage);
      setStage("error");
      toast.error(finalMessage);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-muted rounded-xl p-6 w-full max-w-lg border border-border max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xl font-semibold text-foreground">
            Import {object.plural_name || object.name} from CSV
          </h3>
          <button onClick={handleClose} className="text-muted-foreground hover:text-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        {stage === "select" && (
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            className="relative border-2 border-dashed border-border rounded-xl p-8 text-center hover:border-purple-500/50 transition-colors"
          >
            <Upload className="w-10 h-10 text-muted-foreground mx-auto mb-4" />
            <p className="text-foreground font-medium mb-1">Drop your CSV file here</p>
            <p className="text-sm text-muted-foreground mb-4">or click to browse</p>
            <input
              type="file"
              accept=".csv"
              onChange={handleFileInput}
              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            />
            <p className="text-xs text-muted-foreground">
              Columns are matched to {object.name}&apos;s fields by name. Supports CSV files up to 10MB.
            </p>
          </div>
        )}

        {stage === "preview" && mapping && file && (
          <div className="space-y-4">
            <div className="flex items-center gap-3 p-3 rounded-lg bg-accent/50">
              <FileSpreadsheet className="w-6 h-6 text-purple-400 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-foreground font-medium truncate">{file.name}</p>
                <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(1)} KB</p>
              </div>
              <button onClick={reset} className="text-muted-foreground hover:text-foreground text-sm flex-shrink-0">
                Remove
              </button>
            </div>

            <div className="text-sm">
              <h4 className="font-medium text-foreground mb-2">Column mapping</h4>
              <div className="space-y-1 max-h-40 overflow-y-auto">
                {mapping.mapped.map((m) => (
                  <div key={m.header} className="flex items-center gap-2 text-muted-foreground">
                    <CheckCircle2 className="w-3.5 h-3.5 text-green-400 flex-shrink-0" />
                    <span className="text-foreground">{m.header}</span>
                    <span>&rarr;</span>
                    <span>{m.fieldName}</span>
                  </div>
                ))}
                {mapping.unmapped.map((h) => (
                  <div key={h} className="flex items-center gap-2 text-muted-foreground">
                    <AlertCircle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0" />
                    <span>{h}</span>
                    <span>— no matching field, will be ignored</span>
                  </div>
                ))}
              </div>
            </div>

            {mapping.missingRequired.length > 0 && (
              <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-400">
                Missing a column for required field(s): {mapping.missingRequired.join(", ")}
              </div>
            )}

            <div className="flex gap-3 pt-2">
              <button
                onClick={handleClose}
                className="flex-1 px-4 py-2 border border-border text-foreground rounded-lg hover:bg-accent transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirm}
                disabled={mapping.missingRequired.length > 0}
                className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:bg-purple-600/50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
              >
                Confirm import
              </button>
            </div>
          </div>
        )}

        {stage === "importing" && (
          <div className="flex flex-col items-center justify-center py-10 gap-3">
            <Loader2 className="w-8 h-8 text-purple-400 animate-spin" />
            <p className="text-muted-foreground">Importing...</p>
          </div>
        )}

        {stage === "success" && result && (
          <div className="space-y-4">
            <div className="flex items-center justify-center py-4">
              <div className="w-12 h-12 rounded-full bg-green-500/20 flex items-center justify-center">
                <CheckCircle2 className="w-7 h-7 text-green-400" />
              </div>
            </div>
            <div className="text-left bg-background/50 rounded-lg p-4 space-y-1 text-sm">
              <div className="text-foreground">Rows processed: {result.total_rows}</div>
              <div className="text-green-400">Created: {result.created}</div>
              <div className="text-muted-foreground">Duplicates skipped: {result.duplicates}</div>
              {result.invalid_emails > 0 && (
                <div className="text-amber-400">Invalid rows: {result.invalid_emails}</div>
              )}
              {result.errors > 0 && <div className="text-red-400">Errors: {result.errors}</div>}
              {result.unmapped_headers.length > 0 && (
                <div className="text-muted-foreground">
                  Ignored columns (no matching field): {result.unmapped_headers.join(", ")}
                </div>
              )}
            </div>
            <button
              onClick={handleClose}
              className="w-full px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors"
            >
              Done
            </button>
          </div>
        )}

        {stage === "error" && (
          <div className="space-y-4">
            <div className="flex items-center justify-center py-4">
              <div className="w-12 h-12 rounded-full bg-red-500/20 flex items-center justify-center">
                <AlertCircle className="w-7 h-7 text-red-400" />
              </div>
            </div>
            <p className="text-sm text-red-400 text-center">{errorMsg}</p>
            <div className="flex gap-3">
              <button
                onClick={handleClose}
                className="flex-1 px-4 py-2 border border-border text-foreground rounded-lg hover:bg-accent transition-colors"
              >
                Close
              </button>
              <button
                onClick={reset}
                className="flex-1 px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded-lg transition-colors"
              >
                Try again
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
