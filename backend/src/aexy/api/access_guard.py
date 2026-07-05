"""Reusable FastAPI dependencies for enforcing workspace app (module) access.

Workspace admins can disable a module for the whole workspace, but that toggle
was never enforced on the API — only the sidebar hid the module. These
dependencies close the API hole:

- ``require_app_access`` for routers whose paths carry ``{workspace_id}``.
- ``require_app_access_sprint_scoped`` for routers whose paths carry
  ``{sprint_id}``/``{team_id}`` and resolve the workspace server-side.
- ``require_app_access_document_scoped`` for routers whose paths carry
  ``{document_id}``.
- ``ensure_app_enabled`` for endpoints that resolve the workspace id
  themselves (body/query params, or via a referenced entity).
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.developers import get_current_developer
from aexy.core.database import get_db
from aexy.models.app_definitions import APP_CATALOG
from aexy.models.developer import Developer
from aexy.models.documentation import Document
from aexy.models.sprint import Sprint
from aexy.models.team import Team
from aexy.services.app_access_service import AppAccessService


def _validate_app_id(app_id: str) -> None:
    """Fail loudly at import/startup: a typo'd app id would otherwise make the
    guard silently never enforce (check_workspace_app_enabled defaults to True
    for unknown ids)."""
    if app_id not in APP_CATALOG:
        raise ValueError(f"Unknown app id {app_id!r}: not in APP_CATALOG")


async def ensure_app_enabled(
    db: AsyncSession, workspace_id: str, app_id: str
) -> None:
    """Raise 403 when `app_id` is disabled workspace-wide.

    Enforces the workspace-level module toggle only (not per-role/per-member
    access) — that matches the reported bug ("disabling a module for the
    workspace doesn't block access") and avoids over-restricting users whose
    role bundle happens not to enable an app.
    """
    _validate_app_id(app_id)
    if not await AppAccessService(db).check_workspace_app_enabled(
        str(workspace_id), app_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"The {app_id} module is disabled for this workspace",
        )


def require_app_access(app_id: str):
    """Return a dependency that 403s when `app_id` is disabled for the workspace.

    Requires the caller to be authenticated (via get_current_developer) and
    `{workspace_id}` in the route path, e.g.:

        api_router.include_router(
            crm_router, dependencies=[Depends(require_app_access("crm"))]
        )
    """
    _validate_app_id(app_id)

    async def _guard(
        workspace_id: str,
        current_developer: Developer = Depends(get_current_developer),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        await ensure_app_enabled(db, workspace_id, app_id)

    return _guard


def require_app_access_sprint_scoped(app_id: str):
    """Like `require_app_access`, for routers whose paths carry `{sprint_id}`
    and/or `{team_id}` instead of `{workspace_id}` (sprint analytics, planning
    poker, retrospectives): resolves the workspace server-side.

    Deliberately does NOT depend on get_current_developer: planning poker's
    websocket authenticates via token after the handshake, and a bearer-header
    dependency would reject every browser websocket even when the app is
    enabled. Endpoint-level auth still applies. Unknown/missing ids are left
    for the endpoint to 404.
    """
    _validate_app_id(app_id)

    async def _guard(
        sprint_id: str | None = None,
        team_id: str | None = None,
        db: AsyncSession = Depends(get_db),
    ) -> None:
        workspace_id = None
        if team_id:
            workspace_id = (
                await db.execute(select(Team.workspace_id).where(Team.id == team_id))
            ).scalar_one_or_none()
        elif sprint_id:
            workspace_id = (
                await db.execute(
                    select(Sprint.workspace_id).where(Sprint.id == sprint_id)
                )
            ).scalar_one_or_none()
        if workspace_id:
            await ensure_app_enabled(db, str(workspace_id), app_id)

    return _guard


def require_app_access_document_scoped(app_id: str):
    """Like `require_app_access`, for routers whose paths carry `{document_id}`
    (collaboration): resolves the document's workspace server-side.

    Auth-free for the same websocket reason as the sprint-scoped variant.
    """
    _validate_app_id(app_id)

    async def _guard(
        document_id: str | None = None,
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if not document_id:
            return
        workspace_id = (
            await db.execute(
                select(Document.workspace_id).where(Document.id == document_id)
            )
        ).scalar_one_or_none()
        if workspace_id:
            await ensure_app_enabled(db, str(workspace_id), app_id)

    return _guard
