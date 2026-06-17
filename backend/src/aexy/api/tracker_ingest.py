"""Aexy Tracker — ingest API.

The macOS Tracker client uploads append-only, idempotent event batches; the
server stores them durably and a downstream Temporal/LangGraph pipeline enriches
and attributes them (docs/aexy-tracker.md §5). This router covers ingest only:
enrollment, batch ingest, evidence presign, heartbeat (config pull), and sync.

Contract: docs/api/tracker-ingest.md.
"""

import logging
import time
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.developers import get_current_developer
from aexy.core.config import get_settings
from aexy.core.database import get_db
from aexy.models.developer import Developer
from aexy.models.project import Project, ProjectMember
from aexy.models.tracker_event import TrackerDevice, TrackerEvent
from aexy.schemas.tracker_ingest import (
    DeviceConfig,
    DeviceEnrollRequest,
    DeviceEnrollResponse,
    EventBatchRequest,
    EventBatchResponse,
    EventRecord,
    EvidencePresignRequest,
    EvidencePresignResponse,
    RejectedEvent,
    SyncStatusResponse,
    TrackerProjectResponse,
)
from aexy.services.storage_service import get_storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tracker", tags=["tracker-ingest"])

SCHEMA_VERSION_MAJOR = "1"
SUPPORTED_SCHEMA_PREFIXES = ("1.",)

# ts must fall within [now - 30d, now + 5m] (clock-skew + backfill guard).
_TS_PAST_LIMIT = timedelta(days=30)
_TS_FUTURE_LIMIT = timedelta(minutes=5)

# Rate limits (sliding window, fail-open) — see docs/api/tracker-ingest.md §6.
_RL_WINDOW_S = 60
_RL_BATCH_PER_DEVICE = 30
_RL_BATCH_PER_PROJECT = 600
_RL_EVENTS_PER_PROJECT = 50_000
_RL_PRESIGN_PER_DEVICE = 60

_redis_client: redis.Redis | None = None


async def _get_redis() -> redis.Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        settings = get_settings()
        _redis_client = redis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=2
        )
        await _redis_client.ping()
        return _redis_client
    except Exception:
        logger.warning("Redis unavailable for tracker rate limiting")
        return None


async def _check_rate_limit(key: str, max_count: int, weight: int = 1) -> bool:
    """Sliding-window limiter. Fails open if Redis is down (matches GTM ingest)."""
    r = await _get_redis()
    if r is None:
        return True
    now = time.time()
    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(key, 0, now - _RL_WINDOW_S)
        pipe.zcard(key)
        # Represent weighted cost as `weight` distinct members.
        for i in range(weight):
            pipe.zadd(key, {f"{now}:{i}": now})
        pipe.expire(key, _RL_WINDOW_S + 10)
        results = await pipe.execute()
        return results[1] < max_count
    except Exception:
        return True


_CONFIG_FIELDS = (
    "sample_interval_s",
    "screenshot_policy",
    "screenshot_every_n_samples",
    "idle_threshold_s",
    "paused",
    "excluded_bundle_ids",
)


def _apply_project_config(device: TrackerDevice, cfg: dict) -> None:
    """Seed a device's capture config from a project's ``tracker_config`` defaults.

    Only keys present in ``cfg`` are applied, so a project with no configured
    defaults leaves the model defaults intact.
    """
    if not cfg:
        return
    for key in _CONFIG_FIELDS:
        if key in cfg:
            setattr(device, key, cfg[key])


def _device_config(device: TrackerDevice) -> DeviceConfig:
    return DeviceConfig(
        config_etag=device.config_etag,
        sample_interval_s=device.sample_interval_s,
        screenshot_policy=device.screenshot_policy,
        screenshot_every_n_samples=device.screenshot_every_n_samples,
        idle_threshold_s=device.idle_threshold_s,
        paused=device.paused,
        excluded_bundle_ids=device.excluded_bundle_ids or [],
    )


async def _require_project_membership(
    db: AsyncSession, developer_id: str, project_id: str
) -> Project:
    """Resolve a project the developer is a member of with Tracker enabled."""
    project = await db.get(Project, project_id)
    if project is None or not project.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    member = await db.scalar(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.developer_id == developer_id,
            ProjectMember.status == "active",
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this project")

    if not (project.settings or {}).get("tracker_enabled"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Tracker module not enabled for this project"
        )
    return project


async def _resolve_device(
    db: AsyncSession, developer: Developer, device_id: str
) -> TrackerDevice:
    device = await db.get(TrackerDevice, device_id)
    if device is None or device.developer_id != developer.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not enrolled")
    return device


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/projects", response_model=list[TrackerProjectResponse])
async def list_tracker_projects(
    developer: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Projects the developer can bind a device to (Tracker module enabled)."""
    rows = await db.execute(
        select(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            ProjectMember.developer_id == developer.id,
            ProjectMember.status == "active",
            Project.is_active.is_(True),
            Project.settings["tracker_enabled"].astext == "true",
        )
    )
    projects = rows.scalars().all()
    return [
        TrackerProjectResponse(id=p.id, name=p.name, slug=p.slug) for p in projects
    ]


@router.post(
    "/devices:enroll",
    response_model=DeviceEnrollResponse,
    status_code=status.HTTP_201_CREATED,
)
async def enroll_device(
    data: DeviceEnrollRequest,
    developer: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Register (or re-bind) a device to a Tracker-enabled project."""
    project = await _require_project_membership(db, developer.id, data.project_id)
    # Seed the device's capture config from the project's defaults (if any).
    project_cfg = (project.settings or {}).get("tracker_config") or {}

    device = await db.get(TrackerDevice, data.device_id)
    if device is None:
        device = TrackerDevice(
            id=data.device_id,
            developer_id=developer.id,
            project_id=data.project_id,
            name=data.name,
            platform=data.platform,
        )
        _apply_project_config(device, project_cfg)
        db.add(device)
    else:
        if device.developer_id != developer.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Device belongs to another developer"
            )
        # Re-enrollment can re-point the device at a different project; refresh
        # its capture config from that project's defaults.
        device.project_id = data.project_id
        device.name = data.name or device.name
        _apply_project_config(device, project_cfg)
    await db.commit()
    await db.refresh(device)

    return DeviceEnrollResponse(
        device_id=device.id,
        project_id=device.project_id,
        config=_device_config(device),
    )


@router.post("/events:batch", response_model=EventBatchResponse)
async def ingest_batch(
    batch: EventBatchRequest,
    developer: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Ingest a batch of event records. Idempotent on event_id; partial-success."""
    if not any(batch.schema_version.startswith(p) for p in SUPPORTED_SCHEMA_PREFIXES):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Unsupported schema_version {batch.schema_version}",
        )

    device = await _resolve_device(db, developer, batch.device_id)

    # Rate limiting — device, project request count, project event volume.
    n = len(batch.events)
    if not await _check_rate_limit(
        f"trk:batch:device:{device.id}", _RL_BATCH_PER_DEVICE
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")
    if not await _check_rate_limit(
        f"trk:batch:project:{device.project_id}", _RL_BATCH_PER_PROJECT
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")
    if not await _check_rate_limit(
        f"trk:events:project:{device.project_id}", _RL_EVENTS_PER_PROJECT, weight=n
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Event volume exceeded")

    now = datetime.now(timezone.utc)
    past_floor = now - _TS_PAST_LIMIT
    future_ceil = now + _TS_FUTURE_LIMIT

    # Validate per-event; collect rejects without failing the batch.
    rejected: list[RejectedEvent] = []
    candidates: list[EventRecord] = []
    seen_in_batch: set[str] = set()
    in_batch_dupes = 0
    for evt in batch.events:
        ts = evt.ts if evt.ts.tzinfo else evt.ts.replace(tzinfo=timezone.utc)
        if ts < past_floor or ts > future_ceil:
            rejected.append(RejectedEvent(event_id=evt.event_id, reason="ts_out_of_range"))
            continue
        if evt.event_id in seen_in_batch:
            # Duplicate within the same batch — keep the first, drop the rest.
            # Counted as a duplicate so accepted+duplicates+rejected reconciles.
            in_batch_dupes += 1
            continue
        seen_in_batch.add(evt.event_id)
        candidates.append(evt)

    # Which candidate ids already exist (idempotency)?
    existing_ids: set[str] = set()
    if candidates:
        ids = [e.event_id for e in candidates]
        rows = await db.execute(
            select(TrackerEvent.id).where(
                TrackerEvent.project_id == device.project_id,
                TrackerEvent.device_id == device.id,
                TrackerEvent.id.in_(ids),
            )
        )
        existing_ids = set(rows.scalars().all())

    accepted = 0
    max_seq = device.server_seq
    for evt in candidates:
        ts = evt.ts if evt.ts.tzinfo else evt.ts.replace(tzinfo=timezone.utc)
        max_seq = max(max_seq, evt.client_seq)
        if evt.event_id in existing_ids:
            continue
        db.add(
            TrackerEvent(
                id=evt.event_id,
                project_id=device.project_id,
                developer_id=developer.id,
                device_id=device.id,
                client_seq=evt.client_seq,
                ts=ts,
                interval_s=evt.interval_s,
                active_app=evt.active_app.model_dump(),
                file_context=evt.file_context.model_dump() if evt.file_context else None,
                dev_context=evt.dev_context.model_dump() if evt.dev_context else None,
                browser=evt.browser.model_dump() if evt.browser else None,
                input_cadence=evt.input_cadence.model_dump() if evt.input_cadence else None,
                meeting=evt.meeting.model_dump() if evt.meeting else None,
                system=evt.system.model_dump() if evt.system else None,
                evidence_ref=evt.evidence_ref,
                received_at=now,
            )
        )
        accepted += 1

    device.server_seq = max_seq
    device.last_seen_at = now
    await db.commit()

    # Kick the AI enrich/attribute loop for this project (fire-and-forget).
    # The time-bucketed workflow_id coalesces concurrent batches so we don't
    # spawn a workflow per request; a periodic sweep is the safety net.
    if accepted:
        try:
            from aexy.temporal.dispatch import dispatch
            from aexy.temporal.task_queues import TaskQueue
            from aexy.temporal.activities.tracker_enrich import EnrichTrackerEventsInput

            bucket = int(now.timestamp() // 60)
            await dispatch(
                "enrich_attribute_tracker_events",
                EnrichTrackerEventsInput(project_id=device.project_id),
                task_queue=TaskQueue.ANALYSIS,
                workflow_id=f"tracker-enrich-{device.project_id}-{bucket}",
            )
        except Exception:  # noqa: BLE001 — ingest must never fail on dispatch
            logger.warning("Failed to dispatch tracker enrich loop", exc_info=True)

    return EventBatchResponse(
        accepted=accepted,
        duplicates=len(existing_ids) + in_batch_dupes,
        rejected=rejected,
        server_seq=device.server_seq,
        next_poll_after_s=device.sample_interval_s,
        config_etag=device.config_etag,
    )


@router.post("/devices:heartbeat", response_model=DeviceConfig)
async def heartbeat(
    device_id: str,
    developer: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Liveness ping + config pull (interval, screenshot policy, pause)."""
    device = await _resolve_device(db, developer, device_id)
    device.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return _device_config(device)


@router.get("/sync/status", response_model=SyncStatusResponse)
async def sync_status(
    device_id: str,
    developer: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Server high-water mark so the client can self-heal its local cursor."""
    device = await _resolve_device(db, developer, device_id)
    return SyncStatusResponse(
        device_id=device.id,
        server_seq=device.server_seq,
        last_seen_at=device.last_seen_at,
    )


@router.post("/evidence:presign", response_model=EvidencePresignResponse)
async def presign_evidence(
    data: EvidencePresignRequest,
    device_id: str,
    developer: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Presigned RustFS PUT URL for an optional screenshot artifact."""
    device = await _resolve_device(db, developer, device_id)
    if not await _check_rate_limit(
        f"trk:presign:device:{device.id}", _RL_PRESIGN_PER_DEVICE
    ):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded")

    expires_in = 300
    evidence_ref = f"ev_{device.project_id}_{device.id}_{data.event_id}"
    key = f"tracker-evidence/{device.project_id}/{device.id}/{data.event_id}.webp"

    storage = get_storage_service()
    if not storage.is_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Evidence storage not configured"
        )
    url = storage.generate_presigned_put_url(key, data.content_type, expires_in)
    if url is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Failed to presign evidence upload"
        )

    return EvidencePresignResponse(
        evidence_ref=evidence_ref, upload_url=url, expires_in_s=expires_in
    )
