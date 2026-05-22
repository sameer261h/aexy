"""Unit test for `DocumentSyncService.get_sync_type_for_developer`.

This is the gateway method that routes a developer to one of:
  - REAL_TIME    (Premium / plans with enable_real_time_sync=True)
  - DAILY_BATCH  (Pro / Team tier)
  - MANUAL       (Free tier, no plan, anonymous)

Audit found the entire DocumentSyncService had zero coverage. Spec 5
pins the plan-tier routing — the policy that decides who gets
auto-regenerate. The queue-management methods (queue_document_for_sync,
get_pending_sync_queue, mark_sync_*) are DB-heavy and covered indirectly
by the frontend "pending changes banner" spec.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aexy.models.plan import PlanTier
from aexy.services.document_sync_service import (
    DocumentSyncService,
    SyncTriggerType,
)


def make_service_with_plan(plan: SimpleNamespace | None):
    """Build a DocumentSyncService whose LimitsService returns the given
    plan when asked. Bypasses the DB session entirely."""
    svc = DocumentSyncService.__new__(DocumentSyncService)  # skip __init__
    svc.db = MagicMock()
    svc.limits_service = MagicMock()
    developer = (
        SimpleNamespace(plan=plan) if plan is not None else None
    )
    svc.limits_service.get_developer_with_plan = AsyncMock(return_value=developer)
    return svc


class TestGetSyncTypeForDeveloper:
    @pytest.mark.asyncio
    async def test_premium_plan_gets_real_time(self):
        plan = SimpleNamespace(enable_real_time_sync=True, tier=PlanTier.PRO.value)
        svc = make_service_with_plan(plan)
        assert (
            await svc.get_sync_type_for_developer("dev-1")
            == SyncTriggerType.REAL_TIME
        )

    @pytest.mark.asyncio
    async def test_pro_tier_without_real_time_gets_daily_batch(self):
        plan = SimpleNamespace(enable_real_time_sync=False, tier=PlanTier.PRO.value)
        svc = make_service_with_plan(plan)
        assert (
            await svc.get_sync_type_for_developer("dev-1")
            == SyncTriggerType.DAILY_BATCH
        )

    @pytest.mark.asyncio
    async def test_enterprise_tier_without_real_time_gets_daily_batch(self):
        """Enterprise tier (without explicit real-time flag) gets the
        batch tier — this branch was previously dead because the
        service referenced a non-existent `PlanTier.TEAM`."""
        plan = SimpleNamespace(
            enable_real_time_sync=False,
            tier=PlanTier.ENTERPRISE.value,
        )
        svc = make_service_with_plan(plan)
        assert (
            await svc.get_sync_type_for_developer("dev-1")
            == SyncTriggerType.DAILY_BATCH
        )

    @pytest.mark.asyncio
    async def test_free_tier_gets_manual(self):
        plan = SimpleNamespace(enable_real_time_sync=False, tier=PlanTier.FREE.value)
        svc = make_service_with_plan(plan)
        assert (
            await svc.get_sync_type_for_developer("dev-1")
            == SyncTriggerType.MANUAL
        )

    @pytest.mark.asyncio
    async def test_developer_without_plan_gets_manual(self):
        plan = None
        svc = make_service_with_plan(plan)
        assert (
            await svc.get_sync_type_for_developer("dev-1")
            == SyncTriggerType.MANUAL
        )

    @pytest.mark.asyncio
    async def test_unknown_developer_gets_manual(self):
        """If the developer doesn't exist at all, default to MANUAL —
        we never want to silently grant real-time sync to someone whose
        plan we can't read."""
        svc = DocumentSyncService.__new__(DocumentSyncService)
        svc.db = MagicMock()
        svc.limits_service = MagicMock()
        svc.limits_service.get_developer_with_plan = AsyncMock(return_value=None)
        assert (
            await svc.get_sync_type_for_developer("nonexistent")
            == SyncTriggerType.MANUAL
        )

    @pytest.mark.asyncio
    async def test_real_time_flag_wins_over_low_tier(self):
        """A Free-tier developer with the real-time flag forced on
        (theoretically an admin override) should still route to
        REAL_TIME — the flag is the policy bypass, not the tier check."""
        plan = SimpleNamespace(enable_real_time_sync=True, tier=PlanTier.FREE.value)
        svc = make_service_with_plan(plan)
        assert (
            await svc.get_sync_type_for_developer("dev-1")
            == SyncTriggerType.REAL_TIME
        )
