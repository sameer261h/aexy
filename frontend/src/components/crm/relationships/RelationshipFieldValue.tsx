"use client";

import { useRouter } from "next/navigation";
import { CRMAttribute, CRMObject, RelationshipGroup } from "@/lib/api";
import { RelationshipRecordChip } from "./RelationshipRecordChip";

interface RelationshipFieldValueProps {
  attribute: CRMAttribute;
  /** Already-loaded groups for the viewed record (e.g. from the page-level
   * `useRecordRelationships` call) -- this component never fetches on its
   * own, so callers control dedup/sharing across surfaces. */
  groups: RelationshipGroup[];
  objects: CRMObject[];
  surface?: "detail_view" | "highlights";
}

/** Renders a `record_reference` attribute's current value as authorized
 * relationship chips, reusing the same resolved data, chip component, and
 * non-disclosing placeholder as the Related tab -- this is the
 * `record_reference` counterpart to `FieldRenderer` for surfaces (sidebar,
 * highlights) that need it, without touching the shared field-type registry
 * that Tables/Kanban also depend on. */
export function RelationshipFieldValue({
  attribute,
  groups,
  objects,
  surface = "detail_view",
}: RelationshipFieldValueProps) {
  const router = useRouter();
  const group = groups.find((g) => g.attribute_id === attribute.id);

  if (!group || group.items.length === 0) {
    return (
      <span className="text-muted-foreground">
        {surface === "highlights" ? "Not set" : "—"}
      </span>
    );
  }

  const slugById = new Map(objects.map((o) => [o.id, o.slug]));

  return (
    <div className="flex flex-wrap gap-1.5">
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
  );
}
