"use client";

import { Link2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { CRMObject } from "@/lib/api";
import { useRecordRelationships } from "@/hooks/useCRMRelationships";
import { RelationshipRecordChip } from "./RelationshipRecordChip";

interface RelationshipsPanelProps {
  workspaceId: string | null;
  objectId: string | null;
  recordId: string | null;
  objects: CRMObject[];
}

/** Outgoing `record_reference` relationships on the viewed record, grouped
 * by attribute, rendered as authorized record chips instead of raw IDs. */
export function RelationshipsPanel({ workspaceId, objectId, recordId, objects }: RelationshipsPanelProps) {
  const router = useRouter();
  const { groups, isLoading, error } = useRecordRelationships(workspaceId, objectId, recordId);

  const slugById = new Map(objects.map((o) => [o.id, o.slug]));

  if (isLoading) {
    return <div className="text-sm text-muted-foreground py-4">Loading relationships…</div>;
  }

  if (error) {
    return <div className="text-sm text-red-400 py-4">Couldn&apos;t load relationships.</div>;
  }

  const nonEmptyGroups = groups.filter((g) => g.items.length > 0);

  if (nonEmptyGroups.length === 0) {
    return (
      <div className="text-center py-8">
        <Link2 className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">No outgoing relationships</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {nonEmptyGroups.map((group) => (
        <div key={group.attribute_id}>
          <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
            {group.attribute_name} ({group.total})
          </h4>
          <div className="flex flex-wrap gap-2">
            {group.items.map((item, idx) => (
              <RelationshipRecordChip
                key={`${item.record_id}-${idx}`}
                summary={item}
                objectSlug={item.object_id ? slugById.get(item.object_id) : undefined}
                onClick={
                  item.accessible && item.object_id
                    ? () => {
                        const slug = slugById.get(item.object_id!);
                        if (slug) router.push(`/crm/${slug}/${item.record_id}`);
                      }
                    : undefined
                }
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
