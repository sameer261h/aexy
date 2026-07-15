"""Tests for API tokens: the service, and the `aexy_` auth branch.

API tokens are what the (external) MCP server and other integrations use to
authenticate into the platform, so this exercises the security-sensitive
paths: token generation/hashing, expiry, revocation, and the auth dependency
that turns a raw token into a developer id.
"""

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from aexy.core.config import get_settings
from aexy.models.api_token import ApiToken
from aexy.schemas.api_token import ApiTokenCreate
from aexy.services.api_token_service import ApiTokenService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Service: token generation & hashing
# ---------------------------------------------------------------------------


def test_generate_token_format():
    raw = ApiTokenService._generate_token()
    assert raw.startswith("aexy_")
    hex_part = raw[len("aexy_"):]
    assert len(hex_part) == 32  # token_hex(16) -> 32 hex chars
    int(hex_part, 16)  # parses as hex


def test_generate_token_is_unique():
    tokens = {ApiTokenService._generate_token() for _ in range(100)}
    assert len(tokens) == 100


def test_hash_token_is_deterministic_sha256():
    import hashlib

    raw = "aexy_deadbeef"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert ApiTokenService._hash_token(raw) == expected
    assert len(ApiTokenService._hash_token(raw)) == 64


# ---------------------------------------------------------------------------
# Service: create
# ---------------------------------------------------------------------------


async def test_create_stores_hash_not_raw(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, raw = await service.create(
        sample_developer.id, ApiTokenCreate(name="Claude Code", expires_in_days=90)
    )

    assert raw.startswith("aexy_")
    # The raw token is never persisted — only its hash and a short prefix.
    assert model.token_hash == ApiTokenService._hash_token(raw)
    assert model.token_hash != raw
    assert model.token_prefix == raw[:12]
    assert model.name == "Claude Code"
    assert model.is_active is True


async def test_create_sets_expiry_from_days(db_session, sample_developer):
    service = ApiTokenService(db_session)
    before = datetime.now(timezone.utc)
    model, _ = await service.create(
        sample_developer.id, ApiTokenCreate(name="t", expires_in_days=30)
    )
    assert model.expires_at is not None
    delta = model.expires_at - before
    # ~30 days, allow a small execution window.
    assert timedelta(days=29, hours=23) < delta < timedelta(days=30, minutes=1)


async def test_create_no_expiry_when_days_none(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, _ = await service.create(
        sample_developer.id, ApiTokenCreate(name="t", expires_in_days=None)
    )
    assert model.expires_at is None


# ---------------------------------------------------------------------------
# Service: list
# ---------------------------------------------------------------------------


async def test_list_scoped_to_developer_and_ordered(db_session, sample_developers):
    dev_a, dev_b = sample_developers[0], sample_developers[1]
    service = ApiTokenService(db_session)

    a1, _ = await service.create(dev_a.id, ApiTokenCreate(name="a1"))
    a2, _ = await service.create(dev_a.id, ApiTokenCreate(name="a2"))
    await service.create(dev_b.id, ApiTokenCreate(name="b1"))
    await db_session.commit()

    listed = await service.list(dev_a.id)
    assert {t.name for t in listed} == {"a1", "a2"}  # dev_b's token excluded
    # Newest first.
    assert listed[0].created_at >= listed[1].created_at


# ---------------------------------------------------------------------------
# Service: revoke (soft) vs delete (hard)
# ---------------------------------------------------------------------------


async def test_revoke_marks_inactive_but_keeps_row(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, raw = await service.create(sample_developer.id, ApiTokenCreate(name="t"))
    await db_session.commit()

    assert await service.revoke(sample_developer.id, model.id) is True
    await db_session.commit()

    # Row still present, just inactive.
    listed = await service.list(sample_developer.id)
    assert len(listed) == 1
    assert listed[0].is_active is False
    # A revoked token no longer validates.
    assert await service.validate(raw) is None


async def test_revoke_scoped_to_owner(db_session, sample_developers):
    dev_a, dev_b = sample_developers[0], sample_developers[1]
    service = ApiTokenService(db_session)
    model, _ = await service.create(dev_a.id, ApiTokenCreate(name="t"))
    await db_session.commit()

    # dev_b cannot revoke dev_a's token.
    assert await service.revoke(dev_b.id, model.id) is False
    refreshed = (await service.list(dev_a.id))[0]
    assert refreshed.is_active is True


async def test_revoke_missing_returns_false(db_session, sample_developer):
    service = ApiTokenService(db_session)
    assert await service.revoke(sample_developer.id, "00000000-0000-0000-0000-000000000000") is False


async def test_delete_removes_row(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, _ = await service.create(sample_developer.id, ApiTokenCreate(name="t"))
    await db_session.commit()

    assert await service.delete(sample_developer.id, model.id) is True
    await db_session.commit()
    assert await service.list(sample_developer.id) == []


async def test_delete_scoped_to_owner(db_session, sample_developers):
    dev_a, dev_b = sample_developers[0], sample_developers[1]
    service = ApiTokenService(db_session)
    model, _ = await service.create(dev_a.id, ApiTokenCreate(name="t"))
    await db_session.commit()

    assert await service.delete(dev_b.id, model.id) is False
    assert len(await service.list(dev_a.id)) == 1


# ---------------------------------------------------------------------------
# Service: validate
# ---------------------------------------------------------------------------


async def test_validate_returns_record_for_active_token(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, raw = await service.create(sample_developer.id, ApiTokenCreate(name="t"))
    await db_session.commit()

    validated = await service.validate(raw)
    assert validated is not None
    assert validated.id == model.id
    assert validated.developer_id == sample_developer.id


async def test_validate_rejects_unknown_token(db_session, sample_developer):
    service = ApiTokenService(db_session)
    await service.create(sample_developer.id, ApiTokenCreate(name="t"))
    await db_session.commit()
    assert await service.validate("aexy_not_a_real_token") is None


async def test_validate_rejects_inactive_token(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, raw = await service.create(sample_developer.id, ApiTokenCreate(name="t"))
    model.is_active = False
    await db_session.commit()
    assert await service.validate(raw) is None


async def test_validate_rejects_expired_token(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, raw = await service.create(sample_developer.id, ApiTokenCreate(name="t"))
    model.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    assert await service.validate(raw) is None


async def test_validate_updates_last_used_when_stale(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, raw = await service.create(sample_developer.id, ApiTokenCreate(name="t"))
    # Pretend it was last used 10 minutes ago (older than the 5-min debounce).
    model.last_used_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    await db_session.commit()

    validated = await service.validate(raw)
    assert validated is not None
    assert (datetime.now(timezone.utc) - validated.last_used_at) < timedelta(seconds=30)


async def test_validate_debounces_recent_last_used(db_session, sample_developer):
    service = ApiTokenService(db_session)
    model, raw = await service.create(sample_developer.id, ApiTokenCreate(name="t"))
    recent = datetime.now(timezone.utc) - timedelta(seconds=30)
    model.last_used_at = recent
    await db_session.commit()

    validated = await service.validate(raw)
    assert validated is not None
    # Within the 5-min window, last_used_at is left untouched.
    assert validated.last_used_at == recent


# ---------------------------------------------------------------------------
# Auth branch: get_current_developer_id via the API token, exercised through
# the real endpoints (list requires get_current_developer_id).
# ---------------------------------------------------------------------------

TOKENS_URL = "/api/v1/developers/me/api-tokens"


async def _seed_token(db_session, developer, **overrides):
    service = ApiTokenService(db_session)
    model, raw = await service.create(
        developer.id, ApiTokenCreate(name=overrides.pop("name", "seed"))
    )
    for k, v in overrides.items():
        setattr(model, k, v)
    await db_session.commit()
    return model, raw


async def test_auth_accepts_valid_api_token(client, db_session, sample_developer):
    _, raw = await _seed_token(db_session, sample_developer, name="valid")
    resp = await client.get(TOKENS_URL, headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 200
    assert any(t["name"] == "valid" for t in resp.json())


async def test_auth_rejects_unknown_api_token(client, db_session, sample_developer):
    await _seed_token(db_session, sample_developer)
    resp = await client.get(
        TOKENS_URL, headers={"Authorization": "Bearer aexy_bogus_token"}
    )
    assert resp.status_code == 401


async def test_auth_rejects_expired_api_token(client, db_session, sample_developer):
    _, raw = await _seed_token(
        db_session,
        sample_developer,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    resp = await client.get(TOKENS_URL, headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 401


async def test_auth_rejects_revoked_api_token(client, db_session, sample_developer):
    _, raw = await _seed_token(db_session, sample_developer, is_active=False)
    resp = await client.get(TOKENS_URL, headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 401


async def test_auth_still_accepts_jwt(client, sample_developer):
    settings = get_settings()
    jwt_token = jwt.encode(
        {"sub": sample_developer.id}, settings.secret_key, algorithm=settings.algorithm
    )
    resp = await client.get(TOKENS_URL, headers={"Authorization": f"Bearer {jwt_token}"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Endpoint: revoke & delete round-trips through the API layer
# ---------------------------------------------------------------------------


async def test_revoke_endpoint_soft_disables(client, db_session, sample_developer):
    model, raw = await _seed_token(db_session, sample_developer, name="tok")

    resp = await client.post(
        f"{TOKENS_URL}/{model.id}/revoke",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 204

    # Token is now inactive; the same token can no longer authenticate.
    followup = await client.get(TOKENS_URL, headers={"Authorization": f"Bearer {raw}"})
    assert followup.status_code == 401


async def test_revoke_endpoint_404_for_missing(client, db_session, sample_developer):
    _, raw = await _seed_token(db_session, sample_developer)
    resp = await client.post(
        f"{TOKENS_URL}/00000000-0000-0000-0000-000000000000/revoke",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert resp.status_code == 404


async def test_delete_endpoint_removes_token(client, db_session, sample_developer):
    settings = get_settings()
    jwt_token = jwt.encode(
        {"sub": sample_developer.id}, settings.secret_key, algorithm=settings.algorithm
    )
    auth = {"Authorization": f"Bearer {jwt_token}"}
    model, _ = await _seed_token(db_session, sample_developer, name="tok")

    resp = await client.delete(f"{TOKENS_URL}/{model.id}", headers=auth)
    assert resp.status_code == 204

    listed = await client.get(TOKENS_URL, headers=auth)
    assert listed.json() == []
