"""E3: CRM activity writer populates metadata + actor name.

Two write-side defects the CRM activity feed suffered from:
  - `_log_activity` passed `metadata=` (SQLAlchemy's reserved attr) instead of
    the `activity_metadata` column, so per-activity metadata was silently dropped.
  - actor_name was never resolved from actor_id, so the feed showed a generic
    actor ("User") instead of the person's name.
"""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.crm import CRMActivity, CRMObject, CRMRecord
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace
from aexy.services.crm_service import CRMRecordService


@pytest_asyncio.fixture
async def seed(db_session: AsyncSession):
    dev = Developer(id=str(uuid4()), email=f"c-{uuid4().hex[:6]}@t.com", name="Carol Actor")
    db_session.add(dev)
    await db_session.flush()
    ws = Workspace(id=str(uuid4()), name="W", slug=f"w-{uuid4().hex[:6]}", owner_id=dev.id)
    db_session.add(ws)
    await db_session.flush()
    obj = CRMObject(id=str(uuid4()), workspace_id=ws.id, name="Contact",
                    slug="contact", plural_name="Contacts", object_type="standard")
    db_session.add(obj)
    await db_session.flush()
    rec = CRMRecord(id=str(uuid4()), workspace_id=ws.id, object_id=obj.id, values={"name": "Bob"})
    db_session.add(rec)
    await db_session.flush()
    return {"db": db_session, "dev": dev, "ws": ws, "record_id": rec.id}


async def _log(seed, **kw):
    svc = CRMRecordService(seed["db"])
    await svc._log_activity(
        workspace_id=seed["ws"].id,
        record_id=seed["record_id"],
        activity_type="record.created",
        actor_id=seed["dev"].id,
        metadata={"object_id": "obj-123"},
        **kw,
    )
    row = (await seed["db"].execute(
        select(CRMActivity).where(CRMActivity.record_id == seed["record_id"])
    )).scalars().first()
    return row


@pytest.mark.asyncio
async def test_log_activity_persists_metadata(seed):
    row = await _log(seed)
    assert row.activity_metadata == {"object_id": "obj-123"}


@pytest.mark.asyncio
async def test_log_activity_resolves_actor_name(seed):
    row = await _log(seed)
    assert row.actor_name == "Carol Actor"
