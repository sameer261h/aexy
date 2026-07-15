"""E2.3 audience-from-CRM + E2.6 verified-sender send gating."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.crm import CRMList, CRMListEntry, CRMObject, CRMRecord
from aexy.models.developer import Developer
from aexy.models.email_infrastructure import DomainStatus, SendingDomain
from aexy.models.email_marketing import EmailCampaign, EmailTemplate
from aexy.models.workspace import Workspace
from aexy.services.campaign_service import CampaignService


@pytest_asyncio.fixture
async def ws(db_session: AsyncSession):
    dev = Developer(id=str(uuid4()), email=f"d-{uuid4().hex[:6]}@t.com", name="D")
    db_session.add(dev)
    await db_session.flush()
    w = Workspace(id=str(uuid4()), name="W", slug=f"w-{uuid4().hex[:6]}", owner_id=dev.id)
    db_session.add(w)
    await db_session.commit()
    return w


def _domain(ws_id, status):
    return SendingDomain(id=str(uuid4()), workspace_id=ws_id, domain=f"{uuid4().hex[:6]}.com", status=status)


# --- E2.3: audience from a CRM list ---------------------------------------

@pytest.mark.asyncio
async def test_calculate_audience_counts_crm_list_members(db_session, ws):
    obj = CRMObject(id=str(uuid4()), workspace_id=ws.id, name="Contact",
                    slug="contact", plural_name="Contacts", object_type="standard")
    db_session.add(obj)
    await db_session.flush()
    recs = [CRMRecord(id=str(uuid4()), workspace_id=ws.id, object_id=obj.id,
                      values={"email": f"{i}@ex.com"}) for i in range(3)]
    db_session.add_all(recs)
    lst = CRMList(id=str(uuid4()), workspace_id=ws.id, name="VIPs", slug="vips", object_id=obj.id)
    db_session.add(lst)
    await db_session.flush()
    # Only 2 of the 3 records are on the list.
    db_session.add_all([
        CRMListEntry(id=str(uuid4()), list_id=lst.id, record_id=recs[0].id),
        CRMListEntry(id=str(uuid4()), list_id=lst.id, record_id=recs[1].id),
    ])
    campaign = EmailCampaign(id=str(uuid4()), workspace_id=ws.id, name="C", list_id=lst.id,
                             from_name="Sender", from_email="sender@ex.com")
    db_session.add(campaign)
    await db_session.commit()

    count = await CampaignService(db_session).calculate_audience(campaign)
    assert count == 2


# --- E2.6: verified-sender gate -------------------------------------------

@pytest.mark.asyncio
async def test_has_verified_sender_false_without_domain(db_session, ws):
    assert await CampaignService(db_session)._has_verified_sender(ws.id) is False


@pytest.mark.asyncio
async def test_has_verified_sender_false_for_pending_domain(db_session, ws):
    db_session.add(_domain(ws.id, DomainStatus.PENDING.value))
    await db_session.commit()
    assert await CampaignService(db_session)._has_verified_sender(ws.id) is False


@pytest.mark.asyncio
async def test_has_verified_sender_true_for_verified_domain(db_session, ws):
    db_session.add(_domain(ws.id, DomainStatus.VERIFIED.value))
    await db_session.commit()
    assert await CampaignService(db_session)._has_verified_sender(ws.id) is True


async def _campaign_with_template(db_session, ws_id):
    tmpl = EmailTemplate(
        id=str(uuid4()), workspace_id=ws_id, name="T", slug=f"t-{uuid4().hex[:6]}",
        subject_template="Hi", body_html="<p>hi</p>", template_type="html", variables=[],
    )
    db_session.add(tmpl)
    await db_session.flush()
    c = EmailCampaign(id=str(uuid4()), workspace_id=ws_id, name="C",
                      template_id=tmpl.id, status="draft",
                      from_name="Sender", from_email="sender@ex.com")
    db_session.add(c)
    await db_session.commit()
    return c


@pytest.mark.asyncio
async def test_start_sending_blocked_without_verified_sender(db_session, ws):
    c = await _campaign_with_template(db_session, ws.id)
    with pytest.raises(ValueError, match="verified sending domain"):
        await CampaignService(db_session).start_sending(c.id, ws.id)


@pytest.mark.asyncio
async def test_start_sending_passes_gate_with_verified_sender(db_session, ws):
    db_session.add(_domain(ws.id, DomainStatus.VERIFIED.value))
    c = await _campaign_with_template(db_session, ws.id)
    # Past the sender gate → fails later on empty audience, proving the gate let it through.
    with pytest.raises(ValueError, match="recipients"):
        await CampaignService(db_session).start_sending(c.id, ws.id)
