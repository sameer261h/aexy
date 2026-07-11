"""Duplicate matching for CSV import dry-run.

Batch-checks candidate unique-attribute values against existing, authorized,
row-security-visible records -- reusing `TableAuthService`/row-security
exactly as every other CRM read path does. No fuzzy matching, no
similarity scoring: exact value equality only. Never discloses which
specific record matched, or that an inaccessible record would have
matched -- both cases collapse to "no match" from the caller's
perspective, matching the non-disclosure convention already established
for relationship reference resolution.
"""

from collections.abc import Sequence

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession
from aexy.models.crm import CRMRecord
from aexy.services.data_table_service import DataTableService


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
    ) -> dict[str, bool]:
        """Returns `{value: matched}` for every distinct, non-empty
        candidate value. A value matches only if an authorized,
        row-security-visible record already has that exact value on the
        chosen unique attribute."""
        distinct_values = {v for v in candidate_values if v}
        if not distinct_values:
            return {}

        access = await self.dts.auth.resolve_access(object_id, user_id, workspace_id)
        if not access or not access.can("view"):
            return {v: False for v in distinct_values}

        table = await self.dts.get_table(object_id, workspace_id)
        if not table:
            return {v: False for v in distinct_values}

        stmt = select(CRMRecord).where(
            CRMRecord.workspace_id == workspace_id,
            CRMRecord.object_id == object_id,
            CRMRecord.values[unique_match_attribute_slug].astext.in_(distinct_values),
        )
        stmt = self.dts._apply_row_security(stmt, table, access, user_id=user_id)
        result = await self.db.execute(stmt)
        matched_values = {
            str(record.values.get(unique_match_attribute_slug))
            for record in result.scalars().all()
        }
        return {v: (v in matched_values) for v in distinct_values}


__all__ = ["CsvImportDuplicateService"]
