"use client";

import { Database, Archive, EyeOff, X } from "lucide-react";
import { RelatedRecordSummary } from "@/lib/api";

interface RelationshipRecordChipProps {
  summary: RelatedRecordSummary;
  /** Resolved from the object list already loaded by the parent page --
   * undefined when the object itself hasn't loaded (rare) or isn't
   * navigable yet, in which case the chip renders as non-clickable. */
  objectSlug?: string;
  onClick?: () => void;
  /** When provided, renders a remove control on the chip. Available even
   * for inaccessible/placeholder references -- the stored ID can still be
   * removed from the relationship even though its label can't be shown. */
  onRemove?: () => void;
  removing?: boolean;
}

/** A single resolved (or intentionally opaque) relationship reference.
 * Never discloses a label for an inaccessible/stale/foreign reference --
 * it only ever echoes back the ID the caller's own record already stored. */
export function RelationshipRecordChip({ summary, objectSlug, onClick, onRemove, removing }: RelationshipRecordChipProps) {
  if (!summary.accessible) {
    return (
      <span
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-dashed border-border bg-muted/40 text-xs text-muted-foreground"
        title="This reference is unavailable (missing, archived elsewhere, or not accessible to you)"
      >
        <EyeOff className="h-3 w-3" />
        Unavailable reference
        {onRemove && (
          <button
            type="button"
            onClick={onRemove}
            disabled={removing}
            aria-label="Remove reference"
            className="ml-0.5 rounded hover:bg-muted disabled:opacity-50"
          >
            <X className="h-3 w-3" />
          </button>
        )}
      </span>
    );
  }

  const clickable = !!onClick && !!objectSlug;

  return (
    <span
      className={
        clickable
          ? "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-border bg-muted/50 hover:border-purple-500/50 hover:bg-purple-500/10 text-sm text-foreground transition-colors"
          : "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-border bg-muted/30 text-sm text-muted-foreground"
      }
      title={summary.object_label ? `${summary.object_label}: ${summary.record_label}` : summary.record_label ?? undefined}
    >
      <button type="button" onClick={onClick} disabled={!clickable} className="inline-flex items-center gap-1.5 disabled:cursor-default">
        <Database className="h-3 w-3 text-purple-400 shrink-0" />
        <span className="truncate max-w-[220px]">{summary.record_label}</span>
        {summary.is_archived && (
          <Archive className="h-3 w-3 text-muted-foreground shrink-0" aria-label="Archived" />
        )}
      </button>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          disabled={removing}
          aria-label="Remove reference"
          className="rounded hover:bg-muted disabled:opacity-50"
        >
          <X className="h-3 w-3" />
        </button>
      )}
    </span>
  );
}
