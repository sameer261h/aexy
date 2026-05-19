"use client";

import { useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Wrench,
  CheckCircle,
  XCircle,
  Copy,
  Check,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ToolCallDisplayProps {
  toolName: string;
  input?: Record<string, unknown>;
  output?: unknown;
  status?: "running" | "completed" | "error";
  /** Wall-clock duration of the tool call in ms. When provided, the
   *  header shows a faint duration badge so users get an APM-style
   *  read on which tool was slow without expanding every row. */
  durationMs?: number;
  defaultExpanded?: boolean;
}

// Inline preview for the tool input — first key=value pair as a one-
// liner, truncated. Lets users skim a long thread of tool calls
// without expanding each ("search_contacts: john@example.com" vs an
// opaque "Search Contacts" pill). Skips opaque values (nested objects,
// arrays) because they don't summarize cleanly inline.
function formatInputPreview(input: Record<string, unknown>): string {
  const entries = Object.entries(input).filter(([, v]) => {
    if (v === null || v === undefined) return false;
    if (typeof v === "object") return false;
    return true;
  });
  if (entries.length === 0) return "";
  const [key, value] = entries[0];
  const valueStr = typeof value === "string" ? value : String(value);
  const truncated = valueStr.length > 60 ? `${valueStr.slice(0, 60)}…` : valueStr;
  return `${key}: ${truncated}`;
}

// Best-effort surfacing of an error message buried inside the tool's
// output. Many tools return `{ error: "..." }` or `{ message: "...", type: "Error" }`.
// Falls back to the JSON dump for unrecognized shapes.
function extractErrorMessage(output: unknown): string | null {
  if (!output || typeof output !== "object") return null;
  const o = output as Record<string, unknown>;
  if (typeof o.error === "string") return o.error;
  if (typeof o.message === "string" && (o.type === "Error" || o.error_type)) return o.message;
  return null;
}

function CopyAffordance({ payload }: { payload: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard?.writeText(payload).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        });
      }}
      aria-label={copied ? "Copied" : "Copy JSON"}
      title={copied ? "Copied!" : "Copy JSON"}
      className="ml-auto p-1 text-muted-foreground hover:text-foreground hover:bg-accent rounded transition-colors focus-visible:ring-2 focus-visible:ring-purple-500"
    >
      {copied ? (
        <Check className="h-3 w-3 text-emerald-600 dark:text-emerald-400" aria-hidden />
      ) : (
        <Copy className="h-3 w-3" aria-hidden />
      )}
    </button>
  );
}

export function ToolCallDisplay({
  toolName,
  input,
  output,
  status = "completed",
  durationMs,
  defaultExpanded = false,
}: ToolCallDisplayProps) {
  // Errors auto-expand so the user doesn't have to click into a
  // failing tool to see what went wrong.
  const [isExpanded, setIsExpanded] = useState(
    defaultExpanded || status === "error",
  );

  const formatToolName = (name: string) => {
    return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  };

  const formatJson = (obj: unknown) => {
    try {
      return JSON.stringify(obj, null, 2);
    } catch {
      return String(obj);
    }
  };

  const truncateOutput = (text: string, maxLength = 500) => {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength) + "...";
  };

  const inputPreview = input ? formatInputPreview(input) : "";
  const errorMessage = status === "error" ? extractErrorMessage(output) : null;

  return (
    <div
      className={cn(
        "border rounded-lg overflow-hidden my-2",
        status === "error"
          ? "border-red-500/40 bg-red-500/5"
          : "border-border",
      )}
    >
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        aria-expanded={isExpanded}
        className="w-full flex items-center gap-2 px-3 py-2 bg-accent/50 hover:bg-accent transition text-left"
      >
        <Wrench className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" aria-hidden />
        <span className="text-sm font-medium text-foreground shrink-0">
          {formatToolName(toolName)}
        </span>
        {/* Inline input preview — only shown when there's room and the
            shape summarizes cleanly. Hidden on `<sm` so the header
            stays scannable on mobile. */}
        {inputPreview ? (
          <span className="hidden sm:inline text-xs text-muted-foreground truncate min-w-0">
            {inputPreview}
          </span>
        ) : null}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {typeof durationMs === "number" && status !== "running" ? (
            <span
              className="text-[11px] tabular-nums text-muted-foreground"
              title={`Took ${durationMs}ms`}
            >
              {durationMs < 1000 ? `${durationMs}ms` : `${(durationMs / 1000).toFixed(1)}s`}
            </span>
          ) : null}
          {status === "completed" && (
            <CheckCircle className="h-3 w-3 text-emerald-600 dark:text-emerald-400" aria-hidden />
          )}
          {status === "error" && (
            <XCircle className="h-3 w-3 text-red-600 dark:text-red-400" aria-hidden />
          )}
          {status === "running" && (
            <span
              role="status"
              aria-label="Tool running"
              className="w-3 h-3 border-2 border-purple-500 dark:border-purple-400 border-t-transparent rounded-full motion-safe:animate-spin"
            />
          )}
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden />
          )}
        </div>
      </button>

      {isExpanded && (
        <div className="p-3 space-y-3 bg-muted/50">
          {/* Inline error banner — surface the actual message instead
              of forcing the user to JSON-dive. JSON.dump still
              available below for the raw payload. */}
          {errorMessage ? (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-700 dark:text-red-300 font-mono">
              {errorMessage}
            </div>
          ) : null}

          {input && Object.keys(input).length > 0 && (
            <div>
              <div className="flex items-center text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
                <span>Input</span>
                <CopyAffordance payload={formatJson(input)} />
              </div>
              <pre className="text-xs text-foreground bg-background/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                {formatJson(input)}
              </pre>
            </div>
          )}

          {output !== undefined && (
            <div>
              <div className="flex items-center text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
                <span>Output</span>
                <CopyAffordance
                  payload={typeof output === "string" ? output : formatJson(output)}
                />
              </div>
              <pre className="text-xs text-foreground bg-background/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                {truncateOutput(
                  typeof output === "string" ? output : formatJson(output)
                )}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
