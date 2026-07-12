"""Duplicate matching for CSV import dry-run.

Batch-checks candidate unique-attribute values against existing, authorized,
row-security-visible, non-archived records -- reusing `TableAuthService`/
row-security exactly as every other CRM read path does (matching the
`include_archived=False` default `DataTableService.list_records` uses).
No fuzzy matching, no similarity scoring: exact value equality only.

Never discloses which specific record matched, a matched record's
identifier, or that an inaccessible record would have matched -- an
inaccessible match and no match at all both collapse to "none" from the
caller's perspective, matching the non-disclosure convention already
established for relationship reference resolution. The one signal that IS
disclosed -- and must be, so `update_existing` never silently updates an
arbitrary one of several candidates -- is whether *multiple* accessible
records share the same value ("ambiguous"), without ever revealing how
many or which ones.
"""

from collections.abc import Sequence
from typing import Literal

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession
from aexy.models.crm import CRMRecord
from aexy.services.data_table_service import DataTableService

MatchStatus = Literal["none", "match", "ambiguous"]


class CsvImportDuplicateService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.dts = DataTableService(db)

    async def match_existing_records(
        self,
        object_id: str,
        workspace_id: str,
        user_id: str,
        unique_match_attribute_slug: str,
        candidate_values: Sequence[str],
    ) -> dict[str, MatchStatus]:
        """Returns `{value: status}` for every distinct, non-empty
        candidate value, where status is `"none"` (zero accessible
        matches), `"match"` (exactly one accessible match), or
        `"ambiguous"` (two or more accessible matches -- the caller must
        treat these rows as non-executable rather than guess which record
        was meant)."""
        distinct_values = {v for v in candidate_values if v}
        if not distinct_values:
            return {}

        access = await self.dts.auth.resolve_access(object_id, user_id, workspace_id)
        if not access or not access.can("view"):
            return {v: "none" for v in distinct_values}

        table = await self.dts.get_table(object_id, workspace_id)
        if not table:
            return {v: "none" for v in distinct_values}

        stmt = select(CRMRecord).where(
            CRMRecord.workspace_id == workspace_id,
            CRMRecord.object_id == object_id,
            CRMRecord.is_archived == False,  # noqa: E712 -- SQLAlchemy requires `== False`, not `is False`
            CRMRecord.values[unique_match_attribute_slug].astext.in_(distinct_values),
        )
        stmt = self.dts._apply_row_security(stmt, table, access, user_id=user_id)
        result = await self.db.execute(stmt)
        match_counts: dict[str, int] = {}
        for record in result.scalars().all():
            value = str(record.values.get(unique_match_attribute_slug))
            match_counts[value] = match_counts.get(value, 0) + 1

        def _status(count: int) -> MatchStatus:
            if count == 0:
                return "none"
            if count == 1:
                return "match"
            return "ambiguous"

        return {v: _status(match_counts.get(v, 0)) for v in distinct_values}


__all__ = ["CsvImportDuplicateService", "MatchStatus"]
