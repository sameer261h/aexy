"use client";

import { Link2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { CRMObject, RelationshipMutationErrorDetail } from "@/lib/api";
import { useRecordRelationships, useMutateRelationship } from "@/hooks/useCRMRelationships";
import { RelationshipRecordChip } from "./RelationshipRecordChip";
import { RelationshipCandidatePicker } from "./RelationshipCandidatePicker";

interface RelationshipsPanelProps {
  workspaceId: string | null;
  objectId: string | null;
  recordId: string | null;
  objects: CRMObject[];
}

function mutationErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && Array.isArray((detail as RelationshipMutationErrorDetail).errors)) {
    const errors = (detail as RelationshipMutationErrorDetail).errors;
    if (errors.length > 0) return errors[0].message;
  }
  return "Couldn't save this relationship.";
}

/** Outgoing `record_reference` relationships on the viewed record, grouped
 * by attribute, rendered as authorized record chips instead of raw IDs.
 * Every reference attribute is shown (even with zero items) so a first
 * value can be added; single-cardinality groups hide the picker once set. */
export function RelationshipsPanel({ workspaceId, objectId, recordId, objects }: RelationshipsPanelProps) {
  const router = useRouter();
  const { groups, isLoading, error } = useRecordRelationships(workspaceId, objectId, recordId);
  const { mutate, isPending, error: mutationError, variables } = useMutateRelationship(
    workspaceId, objectId, recordId
  );

  const slugById = new Map(objects.map((o) => [o.id, o.slug]));

  if (isLoading) {
    return <div className="text-sm text-muted-foreground py-4">Loading relationships…</div>;
  }

  if (error) {
    return <div className="text-sm text-red-400 py-4">Couldn&apos;t load relationships.</div>;
  }

  if (groups.length === 0) {
    return (
      <div className="text-center py-8">
        <Link2 className="h-8 w-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">No relationship fields on this record type</p>
      </div>
    );
  }

  const handleRemove = (attributeId: string, currentIds: string[], allowMultiple: boolean, removeId: string) => {
    if (!recordId) return;
    const nextIds = currentIds.filter((id) => id !== removeId);
    mutate({ attributeId, value: allowMultiple ? nextIds : null });
  };

  const handleAdd = (attributeId: string, currentIds: string[], allowMultiple: boolean, addId: string) => {
    if (!recordId) return;
    mutate({ attributeId, value: allowMultiple ? [...currentIds, addId] : addId });
  };

  return (
    <div className="space-y-6">
      {groups.map((group) => {
        const currentIds = group.items.map((i) => i.record_id);
        const showPicker = group.allow_multiple || group.items.length === 0;
        const groupPending = isPending && variables?.attributeId === group.attribute_id;
        const groupError = variables?.attributeId === group.attribute_id ? mutationError : null;

        return (
          <div key={group.attribute_id}>
            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2">
              {group.attribute_name} ({group.total})
            </h4>
            {group.items.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2">
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
                    onRemove={() => handleRemove(group.attribute_id, currentIds, group.allow_multiple, item.record_id)}
                    removing={isPending}
                  />
                ))}
              </div>
            )}
            {showPicker && (
              <RelationshipCandidatePicker
                workspaceId={workspaceId}
                objectId={objectId}
                targetObjectId={group.target_object_id}
                excludeRecordId={recordId ?? undefined}
                excludeIds={currentIds}
                placeholder={`Search ${group.attribute_name.toLowerCase()}…`}
                onSelect={(candidate) => handleAdd(group.attribute_id, currentIds, group.allow_multiple, candidate.record_id)}
              />
            )}
            {groupPending && <p className="text-xs text-muted-foreground mt-1">Saving…</p>}
            {!!groupError && (
              <p className="text-xs text-red-400 mt-1">{mutationErrorMessage(groupError)}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
