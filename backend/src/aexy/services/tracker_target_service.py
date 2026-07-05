"""Aexy Tracker — target-hours resolution + admin CRUD."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.tracker_target import TrackerTargetHours
from aexy.schemas.tracker_target import (
    DEFAULT_TARGET_HOURS,
    TargetHoursOverride,
    TargetHoursResolved,
)


class TrackerTargetService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _rows(self, workspace_id: str) -> list[TrackerTargetHours]:
        result = await self.db.execute(
            select(TrackerTargetHours).where(
                TrackerTargetHours.workspace_id == workspace_id
            )
        )
        return list(result.scalars().all())

    async def resolve(
        self, workspace_id: str, developer_id: str, project_id: str | None
    ) -> TargetHoursResolved:
        """Most-specific-first: developer → project → workspace → hard default."""
        rows = await self._rows(workspace_id)

        dev = next(
            (r for r in rows if r.developer_id == developer_id and r.project_id is None),
            None,
        )
        if dev is not None:
            return TargetHoursResolved(
                target_hours_per_day=float(dev.target_hours_per_day), source="developer"
            )

        if project_id:
            proj = next(
                (r for r in rows if r.project_id == project_id and r.developer_id is None),
                None,
            )
            if proj is not None:
                return TargetHoursResolved(
                    target_hours_per_day=float(proj.target_hours_per_day), source="project"
                )

        ws_default = next(
            (r for r in rows if r.project_id is None and r.developer_id is None), None
        )
        if ws_default is not None:
            return TargetHoursResolved(
                target_hours_per_day=float(ws_default.target_hours_per_day),
                source="workspace",
            )

        return TargetHoursResolved(
            target_hours_per_day=DEFAULT_TARGET_HOURS, source="default"
        )

    async def list_overrides(self, workspace_id: str) -> list[TargetHoursOverride]:
        rows = await self._rows(workspace_id)
        return [
            TargetHoursOverride(
                id=r.id,
                workspace_id=r.workspace_id,
                project_id=r.project_id,
                developer_id=r.developer_id,
                target_hours_per_day=float(r.target_hours_per_day),
                level=r.level(),
            )
            for r in rows
        ]

    async def upsert(
        self,
        workspace_id: str,
        project_id: str | None,
        developer_id: str | None,
        hours: float,
    ) -> TrackerTargetHours:
        """Create or update the override at exactly one level."""
        query = select(TrackerTargetHours).where(
            TrackerTargetHours.workspace_id == workspace_id,
            TrackerTargetHours.project_id == project_id
            if project_id is not None
            else TrackerTargetHours.project_id.is_(None),
            TrackerTargetHours.developer_id == developer_id
            if developer_id is not None
            else TrackerTargetHours.developer_id.is_(None),
        )
        existing = (await self.db.execute(query)).scalar_one_or_none()
        if existing is not None:
            existing.target_hours_per_day = hours
            row = existing
        else:
            row = TrackerTargetHours(
                workspace_id=workspace_id,
                project_id=project_id,
                developer_id=developer_id,
                target_hours_per_day=hours,
            )
            self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete(self, workspace_id: str, row_id: str) -> bool:
        row = await self.db.get(TrackerTargetHours, row_id)
        if row is None or row.workspace_id != workspace_id:
            return False
        await self.db.delete(row)
        await self.db.commit()
        return True
