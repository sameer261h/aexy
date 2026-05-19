"""Workspace authorization helpers used across API routes.

Centralizes the membership and resource-scope assertions that were
previously inlined across ~6 endpoints during the 0.7.82-0.7.88 leak
audit. Keeping them here makes the audit pattern uniform and
test-friendly:

  - `assert_active_member(db, workspace_id, developer_id)` — the
    "target developer is an active member of this workspace" check
    used by app_access / manager_learning / developer insights.

  - `assert_resource_in_workspace(model, db, resource_id, workspace_id)`
    — the "load by id, assert workspace matches route" pattern used
    in Batch B (24+ endpoints). Returns the row.

Both raise `HTTPException(404)` on miss so callers don't leak existence.
"""

from __future__ import annotations

from typing import Any, Type, TypeVar

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.workspace import WorkspaceMember

_T = TypeVar("_T")


async def assert_active_member(
    db: AsyncSession,
    workspace_id: str,
    developer_id: str,
) -> None:
    """Raise 404 unless `developer_id` is an active member of `workspace_id`.

    Returning 404 (not 403) is intentional — leaking "this developer is in
    a different workspace" is itself a cross-tenant existence oracle. From
    the caller's perspective, an unrelated developer simply doesn't exist.
    """
    result = await db.execute(
        select(WorkspaceMember.developer_id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.developer_id == developer_id,
            WorkspaceMember.status == "active",
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Developer not in this workspace")


async def assert_resource_in_workspace(
    db: AsyncSession,
    model: Type[_T],
    resource_id: Any,
    workspace_id: str,
    *,
    pk_attr: str = "id",
    workspace_attr: str = "workspace_id",
    detail: str = "Not found",
) -> _T:
    """Load `model` by id and 404 unless its workspace matches.

    This is the canonical fix for the Batch-B ID-forgery class: an
    attacker with admin in workspace A passes a resource id that lives in
    workspace B; without this check, the loader returns the row and the
    handler then mutates cross-tenant state. Always:

        resource = await assert_resource_in_workspace(
            db, FormField, field_id, route_workspace_id
        )
    """
    stmt = select(model).where(getattr(model, pk_attr) == resource_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=detail)
    if str(getattr(row, workspace_attr)) != str(workspace_id):
        raise HTTPException(status_code=404, detail=detail)
    return row
