"""Unit tests for the workspace-level module toggle enforced by access_guard."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.access_guard import (
    ensure_app_enabled,
    require_app_access,
    require_app_access_document_scoped,
    require_app_access_sprint_scoped,
)
from aexy.api.tracking import _resolve_tracking_workspace
from aexy.models.developer import Developer
from aexy.models.team import Team
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.app_access_service import (
    AppAccessService,
    clear_app_settings_cache,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """The app_settings TTL cache is module-level state; isolate every test."""
    clear_app_settings_cache()
    yield
    clear_app_settings_cache()


def _svc_with_settings(monkeypatch, settings):
    svc = AppAccessService(db=None)

    async def fake_get_workspace(_ws_id):
        return SimpleNamespace(settings=settings)

    monkeypatch.setattr(svc, "_get_workspace", fake_get_workspace)
    return svc


def _patch_settings(monkeypatch, settings):
    """Patch the workspace lookup for any AppAccessService instance (the
    guards construct their own instance internally)."""

    async def fake_get_workspace(_self, _ws_id):
        return SimpleNamespace(settings=settings)

    monkeypatch.setattr(AppAccessService, "_get_workspace", fake_get_workspace)


# ==================== check_workspace_app_enabled ====================


@pytest.mark.asyncio
async def test_disabled_app_is_blocked(monkeypatch):
    svc = _svc_with_settings(monkeypatch, {"app_settings": {"tickets": False, "crm": True}})
    assert await svc.check_workspace_app_enabled("w1", "tickets") is False  # explicitly off
    assert await svc.check_workspace_app_enabled("w1", "crm") is True       # explicitly on
    assert await svc.check_workspace_app_enabled("w1", "docs") is True      # unset -> default on


@pytest.mark.asyncio
async def test_defaults_enabled_when_no_settings(monkeypatch):
    assert await _svc_with_settings(monkeypatch, None).check_workspace_app_enabled("w2", "tickets") is True
    clear_app_settings_cache()
    assert await _svc_with_settings(monkeypatch, {}).check_workspace_app_enabled("w2", "tickets") is True


@pytest.mark.asyncio
async def test_missing_workspace_defaults_enabled(monkeypatch):
    svc = AppAccessService(db=None)

    async def fake_get_workspace(_ws_id):
        return None

    monkeypatch.setattr(svc, "_get_workspace", fake_get_workspace)
    assert await svc.check_workspace_app_enabled("w3", "tickets") is True


# ==================== app_settings TTL cache ====================


@pytest.mark.asyncio
async def test_app_settings_cache_hits_and_invalidation(monkeypatch):
    calls = {"n": 0}
    svc = AppAccessService(db=None)

    async def fake_get_workspace(_ws_id):
        calls["n"] += 1
        return SimpleNamespace(settings={"app_settings": {"crm": False}})

    monkeypatch.setattr(svc, "_get_workspace", fake_get_workspace)

    assert await svc.check_workspace_app_enabled("w4", "crm") is False
    assert await svc.check_workspace_app_enabled("w4", "crm") is False
    assert calls["n"] == 1  # second lookup served from cache

    clear_app_settings_cache("w4")
    assert await svc.check_workspace_app_enabled("w4", "crm") is False
    assert calls["n"] == 2  # invalidation forces a re-read


# ==================== ensure_app_enabled ====================


@pytest.mark.asyncio
async def test_ensure_app_enabled_raises_403_when_disabled(monkeypatch):
    _patch_settings(monkeypatch, {"app_settings": {"reviews": False}})
    with pytest.raises(HTTPException) as exc:
        await ensure_app_enabled(None, "w5", "reviews")
    assert exc.value.status_code == 403
    assert "reviews module is disabled" in exc.value.detail


@pytest.mark.asyncio
async def test_ensure_app_enabled_passes_when_enabled(monkeypatch):
    _patch_settings(monkeypatch, {"app_settings": {"reviews": True}})
    await ensure_app_enabled(None, "w6", "reviews")  # must not raise


@pytest.mark.asyncio
async def test_ensure_app_enabled_rejects_unknown_app_id():
    with pytest.raises(ValueError, match="not_a_real_app"):
        await ensure_app_enabled(None, "w7", "not_a_real_app")


# ==================== factory-time app_id validation ====================


def test_factories_reject_unknown_app_id_at_creation():
    """A typo'd app id must fail at import/startup, not silently no-op."""
    for factory in (
        require_app_access,
        require_app_access_sprint_scoped,
        require_app_access_document_scoped,
    ):
        with pytest.raises(ValueError, match="not_a_real_app"):
            factory("not_a_real_app")


def test_factories_accept_catalog_app_ids():
    assert callable(require_app_access("crm"))
    assert callable(require_app_access_sprint_scoped("sprints"))
    assert callable(require_app_access_document_scoped("docs"))


# ==================== tracking enforcement path ====================


async def _seed_tracking_workspace(
    db: AsyncSession, *, tracking_enabled: bool, slug: str
) -> tuple[Workspace, Developer, Team]:
    dev = Developer(email=f"{slug}@example.com", name=slug)
    db.add(dev)
    await db.flush()

    ws = Workspace(
        name=f"WS {slug}",
        slug=slug,
        owner_id=dev.id,
        settings={"app_settings": {"tracking": tracking_enabled}},
    )
    db.add(ws)
    await db.flush()

    db.add(
        WorkspaceMember(
            workspace_id=ws.id, developer_id=dev.id, role="member", status="active"
        )
    )
    team = Team(workspace_id=ws.id, name=f"Team {slug}", slug=f"team-{slug}")
    db.add(team)
    await db.commit()
    await db.refresh(ws)
    await db.refresh(team)
    return ws, dev, team


@pytest.mark.asyncio
async def test_resolve_tracking_workspace_blocks_disabled_module(db_session):
    ws, dev, team = await _seed_tracking_workspace(
        db_session, tracking_enabled=False, slug="trk-off"
    )
    with pytest.raises(HTTPException) as exc:
        await _resolve_tracking_workspace(
            db_session, str(dev.id), team_id=str(team.id)
        )
    assert exc.value.status_code == 403
    assert "tracking module is disabled" in exc.value.detail


@pytest.mark.asyncio
async def test_resolve_tracking_workspace_allows_enabled_module(db_session):
    ws, dev, team = await _seed_tracking_workspace(
        db_session, tracking_enabled=True, slug="trk-on"
    )
    resolved = await _resolve_tracking_workspace(
        db_session, str(dev.id), team_id=str(team.id)
    )
    assert resolved == str(ws.id)
