"use client";

import { useState, useEffect } from "react";
import { Link2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { CRMObject } from "@/lib/api";
import { useRecordBacklinks } from "@/hooks/useCRMRelationships";
import { RelationshipRecordChip } from "./RelationshipRecordChip";

const PAGE_LIMIT = 20;

interface BacklinksPanelProps {
  workspaceId: string | null;
  objectId: string | null;
  recordId: string | null;
  objects: CRMObject[];
}

/** Incoming backlinks: authorized records elsewhere in the workspace that
 * reference the viewed record. Derived server-side on every request --
 * never persisted. Server-derived total + pagination, not a loaded-page
 * count. */
export function BacklinksPanel({ workspaceId, objectId, recordId, objects }: BacklinksPanelProps) {
  const router = useRouter();
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    setOffset(0);
  }, [recordId]);

  const { items, total, isLoading, error } = useRecordBacklinks(workspaceId, objectId, recordId, {
    limit: PAGE_LIMIT,
    offset,
  });

  const slugById = new Map(objects.map((o) => [o.id, o.slug]));

  if (isLoading) {
    return <div className="text-sm text-muted-foreground py-4">Loading backlinks…</div>;
  }

  if (error) {
    return <div className="text-sm text-red-400 py-4">Couldn&apos;t load backlinks.</div>;
  }

  if (total === 0) {
    return (
      <div className="text-center py-8">
        <Link2 className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">Nothing else references this record yet</p>
      </div>
    );
  }

  const grouped = items.reduce<Record<string, typeof items>>((acc, item) => {
    const key = item.source_object_label;
    (acc[key] ||= []).push(item);
    return acc;
  }, {});

  return (
    <div className="space-y-5">
      <p className="text-xs text-muted-foreground">{total} referencing record{total === 1 ? "" : "s"}</p>
      {Object.entries(grouped).map(([sourceLabel, groupItems]) => (
        <div key={sourceLabel}>
          <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
            {sourceLabel}
          </h4>
          <div className="flex flex-wrap gap-2">
            {groupItems.map((item, idx) => (
              <RelationshipRecordChip
                key={`${item.record_id}-${idx}`}
                summary={item}
                objectSlug={slugById.get(item.source_object_id)}
                onClick={() => {
                  const slug = slugById.get(item.source_object_id);
                  if (slug) router.push(`/crm/${slug}/${item.record_id}`);
                }}
              />
            ))}
          </div>
        </div>
      ))}

      {total > PAGE_LIMIT && (
        <div className="flex items-center justify-between pt-2 text-xs text-muted-foreground">
          <span>
            Showing {Math.min(offset + 1, total)}–{Math.min(offset + PAGE_LIMIT, total)} of {total}
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - PAGE_LIMIT))}
              disabled={offset === 0}
              className="px-2.5 py-1 border border-border rounded-md hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Previous
            </button>
            <button
              onClick={() => setOffset(offset + PAGE_LIMIT)}
              disabled={offset + PAGE_LIMIT >= total}
              className="px-2.5 py-1 border border-border rounded-md hover:bg-accent disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
