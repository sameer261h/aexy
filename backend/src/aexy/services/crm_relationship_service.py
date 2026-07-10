"""Read-only CRM relationship navigation: resolving `record_reference`
attribute values into authorized summaries, deriving incoming backlinks,
and searching candidate records for a future picker.

No relationship writes, normalization, or persistence live here. Reuses
`DataTableService`/`TableAuthService` for all authorization, row-security,
and search -- it does not duplicate that query engine.
"""

from typing import Any

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.crm import CRMAttribute, CRMObject, CRMRecord, CRMAttributeType
from aexy.services.data_table_service import DataTableService, TableAccess
from aexy.schemas.crm_relationships import (
    RelatedRecordSummary,
    RelationshipGroup,
    RelationshipsResponse,
    BacklinkItem,
    BacklinksResponse,
    CandidateRecord,
    CandidateSearchResponse,
)

# Attribute types whose value is meaningfully displayable as a record label.
# Mirrors the free-text search allowlist in DataTableService -- a record's
# display label should only ever come from a plain textual field.
_LABEL_ATTRIBUTE_TYPES = {
    CRMAttributeType.TEXT.value,
    CRMAttributeType.TEXTAREA.value,
    CRMAttributeType.EMAIL.value,
    CRMAttributeType.PHONE.value,
    CRMAttributeType.PERSON_NAME.value,
    CRMAttributeType.URL.value,
}


def _normalize_reference_ids(raw: Any) -> list[str]:
    """A record_reference value may be stored as a scalar ID string, a list
    of ID strings, or absent -- `allow_multiple` is a UI/config hint, not an
    enforced storage constraint (nothing validates it on write today), so
    this accepts either shape defensively rather than trusting the config."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(v) for v in raw if v]
    if isinstance(raw, str) and raw:
        return [raw]
    return []


def _record_label(record: CRMRecord, attributes: list[CRMAttribute] | None) -> str:
    """Best-effort display label. Prefers `display_name` (the establish
    convention), falling back to the first populated textual attribute so a
    relationship chip is never blank just because the object has no primary
    attribute configured."""
    if record.display_name:
        return record.display_name
    for attr in sorted(attributes or [], key=lambda a: a.position):
        if attr.attribute_type in _LABEL_ATTRIBUTE_TYPES:
            val = record.values.get(attr.slug)
            if val:
                return str(val)[:200]
    return f"Record {str(record.id)[:8]}"


class CRMRelationshipService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.dts = DataTableService(db)

    async def _reference_attributes(self, object_id: str) -> list[CRMAttribute]:
        stmt = (
            select(CRMAttribute)
            .where(
                CRMAttribute.object_id == object_id,
                CRMAttribute.attribute_type == CRMAttributeType.RECORD_REFERENCE.value,
            )
            .order_by(CRMAttribute.position)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _all_attributes(self, object_id: str) -> list[CRMAttribute]:
        """Fresh, explicit query -- deliberately does not rely on
        `CRMObject.attributes` (the relationship collection can be stale for
        an object instance already in the session's identity map from an
        earlier, attribute-less load; this is a pre-existing quirk in the
        shared table/object loading code, out of this feature's scope to
        fix, so label derivation here just sidesteps it)."""
        stmt = (
            select(CRMAttribute)
            .where(CRMAttribute.object_id == object_id)
            .order_by(CRMAttribute.position)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def _resolve_target_ids(
        self,
        target_object_id: str,
        ids: list[str],
        workspace_id: str,
        user_id: str,
    ) -> dict[str, dict[str, Any] | None]:
        """Batch-resolve IDs against one target object in a single query
        (never one query per identifier). Returns None per-ID for anything
        stale, foreign-workspace, row-security-excluded, or fully
        inaccessible -- callers must not use a None entry to derive a label.

        Archived records ARE resolved and returned (with `is_archived=True`)
        rather than treated as inaccessible: an explicit stored reference to
        an archived record is still a meaningful pointer, unlike a listing
        view where archived rows are excluded by default.
        """
        if not ids:
            return {}

        access = await self.dts.auth.resolve_access(target_object_id, user_id, workspace_id)
        if not access or not access.can("view"):
            return {i: None for i in ids}

        target = await self.dts.get_table(target_object_id, workspace_id)
        if not target:
            return {i: None for i in ids}
        target_attrs = await self._all_attributes(target_object_id)

        stmt = select(CRMRecord).where(
            CRMRecord.id.in_(ids),
            CRMRecord.workspace_id == workspace_id,
            CRMRecord.object_id == target_object_id,
        )
        stmt = self.dts._apply_row_security(stmt, target, access, user_id=user_id)
        result = await self.db.execute(stmt)
        found = {str(r.id): r for r in result.scalars().all()}

        out: dict[str, dict[str, Any] | None] = {}
        for i in ids:
            rec = found.get(i)
            if not rec:
                out[i] = None
                continue
            out[i] = {
                "object_id": target_object_id,
                "object_label": target.name,
                "record_label": _record_label(rec, target_attrs),
                "is_archived": rec.is_archived,
            }
        return out

    async def get_relationships(
        self,
        object_id: str,
        record: CRMRecord,
        workspace_id: str,
        user_id: str,
    ) -> RelationshipsResponse:
        """Resolve every `record_reference` attribute on `record`'s own
        object into authorized summaries, preserving stored order."""
        attrs = await self._reference_attributes(object_id)

        per_attr_ids: dict[str, list[str]] = {}
        ids_by_target: dict[str, set[str]] = {}
        for attr in attrs:
            target_object_id = (attr.config or {}).get("targetObjectId")
            if not target_object_id:
                continue
            ids = _normalize_reference_ids(record.values.get(attr.slug))
            per_attr_ids[attr.id] = ids
            ids_by_target.setdefault(target_object_id, set()).update(ids)

        resolved_by_target: dict[str, dict[str, dict[str, Any] | None]] = {}
        for target_object_id, target_ids in ids_by_target.items():
            resolved_by_target[target_object_id] = await self._resolve_target_ids(
                target_object_id, list(target_ids), workspace_id, user_id,
            )

        groups: list[RelationshipGroup] = []
        for attr in attrs:
            target_object_id = (attr.config or {}).get("targetObjectId")
            if not target_object_id:
                continue
            ids = per_attr_ids.get(attr.id, [])
            resolved = resolved_by_target.get(target_object_id, {})
            items = []
            for rid in ids:
                data = resolved.get(rid)
                if data is None:
                    items.append(RelatedRecordSummary(
                        attribute_id=attr.id, record_id=rid, accessible=False,
                    ))
                else:
                    items.append(RelatedRecordSummary(
                        attribute_id=attr.id, record_id=rid, accessible=True,
                        **data,
                    ))
            groups.append(RelationshipGroup(
                attribute_id=attr.id,
                attribute_name=attr.name,
                target_object_id=target_object_id,
                allow_multiple=bool((attr.config or {}).get("allowMultiple")),
                total=len(items),
                items=items,
            ))
        return RelationshipsResponse(groups=groups)

    async def get_backlinks(
        self,
        object_id: str,
        record_id: str,
        workspace_id: str,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
    ) -> BacklinksResponse:
        """Derive authorized records (in this workspace) whose
        `record_reference` value references `record_id`. Never persisted --
        computed fresh from `CRMAttribute.config` + a scoped containment
        query per referencing attribute."""
        attr_stmt = (
            select(CRMAttribute)
            .join(CRMObject, CRMAttribute.object_id == CRMObject.id)
            .where(
                CRMObject.workspace_id == workspace_id,
                CRMAttribute.attribute_type == CRMAttributeType.RECORD_REFERENCE.value,
            )
        )
        attr_result = await self.db.execute(attr_stmt)
        referencing_attrs = [
            a for a in attr_result.scalars().all()
            if (a.config or {}).get("targetObjectId") == object_id
        ]

        source_objects: dict[str, CRMObject | None] = {}
        accesses: dict[str, TableAccess | None] = {}
        for attr in referencing_attrs:
            if attr.object_id not in source_objects:
                source_objects[attr.object_id] = await self.dts.get_table(attr.object_id, workspace_id)
            if attr.object_id not in accesses:
                accesses[attr.object_id] = await self.dts.auth.resolve_access(
                    attr.object_id, user_id, workspace_id,
                )

        authorized_groups: list[tuple[CRMAttribute, CRMObject, TableAccess]] = []
        for attr in referencing_attrs:
            src_obj = source_objects[attr.object_id]
            access = accesses[attr.object_id]
            if src_obj is not None and access is not None and access.can("view"):
                authorized_groups.append((attr, src_obj, access))

        escaped = self.dts._escape_like(record_id)
        contains_pattern = f'%"{escaped}"%'
        attrs_cache: dict[str, list[CRMAttribute]] = {}

        group_plans: list[tuple[CRMAttribute, CRMObject, Any, int]] = []
        for attr, src_obj, access in authorized_groups:
            base_stmt = select(CRMRecord).where(
                CRMRecord.workspace_id == workspace_id,
                CRMRecord.object_id == src_obj.id,
            )
            if not include_archived:
                base_stmt = base_stmt.where(CRMRecord.is_archived == False)
            base_stmt = self.dts._apply_row_security(base_stmt, src_obj, access, user_id=user_id)
            base_stmt = base_stmt.where(
                or_(
                    CRMRecord.values[attr.slug].astext == record_id,
                    CRMRecord.values[attr.slug].astext.ilike(contains_pattern),
                )
            )
            count_stmt = select(func.count()).select_from(base_stmt.subquery())
            count_result = await self.db.execute(count_stmt)
            total = count_result.scalar() or 0
            group_plans.append((attr, src_obj, base_stmt, total))

        overall_total = sum(total for *_, total in group_plans)

        items: list[BacklinkItem] = []
        remaining_skip = offset
        remaining_take = limit
        for attr, src_obj, base_stmt, total in group_plans:
            if remaining_take <= 0:
                break
            if remaining_skip >= total:
                remaining_skip -= total
                continue
            page_stmt = (
                base_stmt.order_by(CRMRecord.created_at.desc())
                .limit(remaining_take)
                .offset(remaining_skip)
            )
            page_result = await self.db.execute(page_stmt)
            if src_obj.id not in attrs_cache:
                attrs_cache[src_obj.id] = await self._all_attributes(src_obj.id)
            for rec in page_result.scalars().all():
                items.append(BacklinkItem(
                    attribute_id=attr.id,
                    record_id=str(rec.id),
                    accessible=True,
                    object_id=src_obj.id,
                    object_label=src_obj.name,
                    record_label=_record_label(rec, attrs_cache[src_obj.id]),
                    is_archived=rec.is_archived,
                    source_object_id=src_obj.id,
                    source_object_label=src_obj.name,
                ))
            remaining_take = limit - len(items)
            remaining_skip = 0

        return BacklinksResponse(items=items, total=overall_total, limit=limit, offset=offset)

    async def search_candidates(
        self,
        target_object_id: str,
        workspace_id: str,
        user_id: str,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
        exclude_record_id: str | None = None,
        exclude_ids: list[str] | None = None,
        include_archived: bool = False,
    ) -> CandidateSearchResponse:
        """Read-only candidate search for a future relationship picker.
        Reuses `DataTableService.list_records`'s existing search/filter/
        row-security engine directly -- no second query engine."""
        access = await self.dts.auth.resolve_access(target_object_id, user_id, workspace_id)
        if not access or not access.can("view"):
            return CandidateSearchResponse(items=[], total=0, limit=limit, offset=offset)

        exclude: list[str] = list(exclude_ids or [])
        if exclude_record_id:
            exclude.append(exclude_record_id)

        records, total = await self.dts.list_records(
            table_id=target_object_id,
            workspace_id=workspace_id,
            search=q,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
            access=access,
            user_id=user_id,
            exclude_ids=exclude or None,
        )

        target_attrs = await self._all_attributes(target_object_id)
        items = [
            CandidateRecord(
                record_id=str(r.id),
                record_label=_record_label(r, target_attrs),
                is_archived=r.is_archived,
            )
            for r in records
        ]
        return CandidateSearchResponse(items=items, total=total, limit=limit, offset=offset)
