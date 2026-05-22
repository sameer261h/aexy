"use client";

import { useState } from "react";
import { Check, X, AlertTriangle, Columns, AlignLeft } from "lucide-react";

import { ProposedEdit } from "@/lib/api";

type DiffMode = "summary" | "unified" | "side-by-side";

interface Props {
  proposal: ProposedEdit;
  onApprove: () => void;
  onReject: (reason?: string) => void;
  isPending?: boolean;
}

/**
 * Diff view for a single proposed edit.
 *
 * UX (per the Part B plan):
 *   - DEFAULT: "section summary" — sections added / removed /
 *     headings changed (cheap, scannable).
 *   - EXPAND: "View full diff" toggles between unified and
 *     side-by-side modes.
 *   - STALE: when `proposal.is_stale` is true, render the merge-
 *     conflict UI — three explicit actions: apply anyway,
 *     regenerate, reject. We currently surface the message + force
 *     the user to opt into Approve; "regenerate" is left as a TODO
 *     follow-up (it'd refire the source's generation pipeline
 *     against the new base content sha).
 */
export function ProposedEditReview({
  proposal,
  onApprove,
  onReject,
  isPending,
}: Props) {
  const [mode, setMode] = useState<DiffMode>("summary");
  const [showRejectForm, setShowRejectForm] = useState(false);
  const [rejectReason, setRejectReason] = useState("");

  const summary = proposal.diff_summary ?? {};
  const sectionsAdded = summary.sections_added ?? [];
  const sectionsRemoved = summary.sections_removed ?? [];
  const headingsChanged = summary.headings_changed ?? [];

  return (
    <div
      data-testid="proposed-edit-review"
      className="border border-border rounded-md bg-background/60 overflow-hidden"
    >
      {proposal.is_stale && (
        <div
          data-testid="stale-conflict-banner"
          className="flex items-start gap-2 px-3 py-2 bg-warning/10 border-b border-warning/30"
        >
          <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" />
          <div className="text-xs text-foreground">
            <div className="font-medium">
              This proposal is out of date with the current document.
            </div>
            <div className="text-muted-foreground">
              The document has been edited since the AI proposed this change.
              Apply anyway if you want to overwrite, or reject and regenerate
              for a fresh proposal that knows about your edits.
            </div>
          </div>
        </div>
      )}

      {/* Diff mode toggle */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-border/50 text-xs">
        <span className="text-muted-foreground mr-2">Diff:</span>
        <button
          type="button"
          data-testid="diff-mode-summary"
          onClick={() => setMode("summary")}
          className={`px-2 py-0.5 rounded transition ${
            mode === "summary"
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Summary
        </button>
        <button
          type="button"
          data-testid="diff-mode-unified"
          onClick={() => setMode("unified")}
          className={`px-2 py-0.5 rounded transition inline-flex items-center gap-1 ${
            mode === "unified"
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <AlignLeft className="h-3 w-3" />
          Unified
        </button>
        <button
          type="button"
          data-testid="diff-mode-side-by-side"
          onClick={() => setMode("side-by-side")}
          className={`px-2 py-0.5 rounded transition inline-flex items-center gap-1 ${
            mode === "side-by-side"
              ? "bg-accent text-foreground"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <Columns className="h-3 w-3" />
          Side-by-side
        </button>
      </div>

      <div className="p-3">
        {mode === "summary" && (
          <DiffSummary
            sectionsAdded={sectionsAdded}
            sectionsRemoved={sectionsRemoved}
            headingsChanged={headingsChanged}
          />
        )}
        {mode === "unified" && (
          <pre
            data-testid="diff-unified-view"
            className="text-xs font-mono text-foreground whitespace-pre-wrap bg-muted/30 rounded p-2 max-h-96 overflow-auto"
          >
            {JSON.stringify(proposal.proposed_content, null, 2)}
          </pre>
        )}
        {mode === "side-by-side" && (
          <div
            data-testid="diff-side-by-side-view"
            className="grid grid-cols-2 gap-2 text-xs font-mono"
          >
            <div className="bg-muted/30 rounded p-2 max-h-96 overflow-auto">
              <div className="text-muted-foreground mb-1 not-italic font-sans">
                Current
              </div>
              <pre className="whitespace-pre-wrap">(use editor view to see current document)</pre>
            </div>
            <div className="bg-muted/30 rounded p-2 max-h-96 overflow-auto">
              <div className="text-muted-foreground mb-1 not-italic font-sans">
                Proposed
              </div>
              <pre className="whitespace-pre-wrap">
                {JSON.stringify(proposal.proposed_content, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 px-3 py-2 border-t border-border/50 bg-muted/20">
        {showRejectForm ? (
          <>
            <input
              type="text"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Reason (optional)"
              data-testid="reject-reason-input"
              className="flex-1 px-2 py-1 text-xs bg-background border border-border rounded text-foreground focus:outline-none focus:border-primary-500"
            />
            <button
              type="button"
              onClick={() => setShowRejectForm(false)}
              className="px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
            >
              Cancel
            </button>
            <button
              type="button"
              data-testid="reject-confirm-button"
              disabled={isPending}
              onClick={() => onReject(rejectReason || undefined)}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-destructive hover:bg-destructive/10 rounded disabled:opacity-50"
            >
              <X className="h-3 w-3" />
              Reject
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              data-testid="reject-button"
              onClick={() => setShowRejectForm(true)}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-muted-foreground hover:text-destructive hover:bg-destructive/10 rounded"
            >
              <X className="h-3 w-3" />
              Reject
            </button>
            <button
              type="button"
              data-testid="approve-button"
              disabled={isPending}
              onClick={onApprove}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-white bg-primary-600 hover:bg-primary-700 rounded disabled:opacity-50"
            >
              <Check className="h-3 w-3" />
              {proposal.is_stale ? "Apply anyway" : "Approve"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function DiffSummary({
  sectionsAdded,
  sectionsRemoved,
  headingsChanged,
}: {
  sectionsAdded: string[];
  sectionsRemoved: string[];
  headingsChanged: string[];
}) {
  const empty =
    sectionsAdded.length === 0 &&
    sectionsRemoved.length === 0 &&
    headingsChanged.length === 0;

  if (empty) {
    return (
      <div data-testid="diff-summary-empty" className="text-xs text-muted-foreground">
        No section summary available for this proposal. Switch to Unified or
        Side-by-side to inspect the full content.
      </div>
    );
  }

  return (
    <div data-testid="diff-summary" className="space-y-2 text-xs">
      {sectionsAdded.length > 0 && (
        <SummaryRow label="Adds" items={sectionsAdded} tone="success" />
      )}
      {sectionsRemoved.length > 0 && (
        <SummaryRow label="Removes" items={sectionsRemoved} tone="destructive" />
      )}
      {headingsChanged.length > 0 && (
        <SummaryRow label="Changes" items={headingsChanged} tone="info" />
      )}
    </div>
  );
}

function SummaryRow({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone: "success" | "destructive" | "info";
}) {
  const toneClasses = {
    success: "text-success",
    destructive: "text-destructive",
    info: "text-foreground",
  }[tone];
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className={`font-medium ${toneClasses}`}>{label}:</span>
      {items.map((it, i) => (
        <span
          key={`${label}-${i}`}
          className="px-1.5 py-0.5 bg-muted/40 rounded text-foreground"
        >
          {it}
        </span>
      ))}
    </div>
  );
}
