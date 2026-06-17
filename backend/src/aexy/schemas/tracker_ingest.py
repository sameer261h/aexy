"""Aexy Tracker — ingest request/response schemas.

See AEXY_TRACKER_INGEST_API.md for the full contract. The client supplies only
raw semantic signals; ``category`` and ``attribution`` are server-derived and
intentionally absent from ``EventRecord``.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

MAX_BATCH_EVENTS = 500


# --------------------------------------------------------------------------- #
# Event sub-objects
# --------------------------------------------------------------------------- #
class ActiveApp(BaseModel):
    name: str = Field(max_length=255)
    bundle_id: str = Field(max_length=255)
    window_title: str | None = Field(default=None, max_length=1024)


class FileContext(BaseModel):
    path: str | None = Field(default=None, max_length=2048)
    repo: str | None = Field(default=None, max_length=255)
    branch: str | None = Field(default=None, max_length=255)


class DevContext(BaseModel):
    terminal_cwd: str | None = Field(default=None, max_length=2048)
    last_command: str | None = Field(default=None, max_length=1024)
    editor_file: str | None = Field(default=None, max_length=2048)


class BrowserContext(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    title: str | None = Field(default=None, max_length=1024)


class InputCadence(BaseModel):
    """Aggregate counts only — never keystroke content (keylogging guard)."""

    model_config = ConfigDict(extra="forbid")
    key_events: int = Field(ge=0)
    mouse_events: int = Field(ge=0)


class MeetingContext(BaseModel):
    in_call: bool = False
    call_app: str | None = Field(default=None, max_length=255)
    calendar_event_id: str | None = Field(default=None, max_length=255)


class SystemContext(BaseModel):
    on_battery: bool | None = None
    displays: int | None = Field(default=None, ge=0)
    online: bool | None = None
    network: str | None = Field(default=None, max_length=32)


# --------------------------------------------------------------------------- #
# Event record + batch
# --------------------------------------------------------------------------- #
class EventRecord(BaseModel):
    # Forward-compat: ignore unknown fields so older servers tolerate newer clients.
    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(max_length=36)
    client_seq: int = Field(ge=0)
    ts: datetime
    interval_s: int = Field(ge=1, le=600)

    active_app: ActiveApp
    file_context: FileContext | None = None
    dev_context: DevContext | None = None
    browser: BrowserContext | None = None
    input_cadence: InputCadence | None = None
    meeting: MeetingContext | None = None
    system: SystemContext | None = None
    evidence_ref: str | None = Field(default=None, max_length=128)
    # category / attribution intentionally omitted — server-derived only.


class EventBatchRequest(BaseModel):
    schema_version: str = Field(max_length=16)
    device_id: str = Field(max_length=36)
    sent_at: datetime
    events: list[EventRecord] = Field(..., max_length=MAX_BATCH_EVENTS)


class RejectedEvent(BaseModel):
    event_id: str
    reason: str


class EventBatchResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: list[RejectedEvent]
    server_seq: int
    next_poll_after_s: int | None = None
    config_etag: str | None = None


# --------------------------------------------------------------------------- #
# Device enrollment / heartbeat / sync
# --------------------------------------------------------------------------- #
class DeviceEnrollRequest(BaseModel):
    device_id: str = Field(max_length=36)
    project_id: str = Field(max_length=36)
    name: str | None = Field(default=None, max_length=255)
    platform: str = Field(default="macos", max_length=32)


class DeviceConfig(BaseModel):
    config_etag: str
    sample_interval_s: int
    screenshot_policy: str
    screenshot_every_n_samples: int
    idle_threshold_s: int
    paused: bool
    excluded_bundle_ids: list[str] = Field(default_factory=list)


class DeviceEnrollResponse(BaseModel):
    device_id: str
    project_id: str
    config: DeviceConfig


class SyncStatusResponse(BaseModel):
    device_id: str
    server_seq: int
    last_seen_at: datetime | None = None


class EvidencePresignRequest(BaseModel):
    event_id: str = Field(max_length=36)
    content_type: str = Field(max_length=64)
    byte_size: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)


class EvidencePresignResponse(BaseModel):
    evidence_ref: str
    upload_url: str
    expires_in_s: int


class TrackerProjectResponse(BaseModel):
    id: str
    name: str
    slug: str


# --------------------------------------------------------------------------- #
# Q&A over tracker history (AEXY_TRACKER.md §5.5)
# --------------------------------------------------------------------------- #
class TrackerQARequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    days: int = Field(default=7, ge=1, le=90)


class TrackerQAResponse(BaseModel):
    answer: str
    days: int
    journals_used: int
    time_entries_used: int


# --------------------------------------------------------------------------- #
# Auto-attributed timesheet (read view over inferred TimeEntry + journals)
# --------------------------------------------------------------------------- #
class TrackerTimesheetEntry(BaseModel):
    id: str
    entry_date: str
    duration_minutes: int
    task_id: str | None = None
    task_title: str | None = None
    description: str | None = None
    confidence_score: float | None = None


class TrackerTimesheetDay(BaseModel):
    date: str
    total_minutes: int
    entries: list[TrackerTimesheetEntry]
    journal: str | None = None


class TrackerTimesheetResponse(BaseModel):
    days: list[TrackerTimesheetDay]
    total_minutes: int
    days_count: int
