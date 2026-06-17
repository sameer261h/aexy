"""Unit tests for Tracker ingest schema validation (pure Pydantic, no DB)."""

import pytest
from pydantic import ValidationError

from aexy.schemas.tracker_ingest import (
    MAX_BATCH_EVENTS,
    EventBatchRequest,
    EventRecord,
    InputCadence,
    TrackerQARequest,
)


def _event_dict(**over):
    d = {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "client_seq": 1,
        "ts": "2026-06-16T10:00:00Z",
        "interval_s": 60,
        "active_app": {"name": "VS Code", "bundle_id": "com.microsoft.VSCode"},
    }
    d.update(over)
    return d


def test_input_cadence_rejects_content_like_extra_fields():
    # Keylogging guard: counts only, extra fields forbidden.
    with pytest.raises(ValidationError):
        InputCadence(key_events=10, mouse_events=5, keystrokes="hello")


def test_input_cadence_accepts_counts():
    c = InputCadence(key_events=10, mouse_events=5)
    assert c.key_events == 10


def test_event_record_ignores_server_derived_fields():
    # category/attribution are server-derived; extra='ignore' drops them.
    er = EventRecord(**_event_dict(category="productive", attribution={"x": 1}))
    assert not hasattr(er, "category")
    assert not hasattr(er, "attribution")


def test_event_record_rejects_out_of_range_interval():
    with pytest.raises(ValidationError):
        EventRecord(**_event_dict(interval_s=601))
    with pytest.raises(ValidationError):
        EventRecord(**_event_dict(interval_s=0))


def test_batch_rejects_more_than_max_events():
    events = [_event_dict() for _ in range(MAX_BATCH_EVENTS + 1)]
    with pytest.raises(ValidationError):
        EventBatchRequest(
            schema_version="1.0",
            device_id="22222222-2222-2222-2222-222222222222",
            sent_at="2026-06-16T10:00:00Z",
            events=events,
        )


def test_batch_accepts_at_limit():
    events = [_event_dict() for _ in range(3)]
    batch = EventBatchRequest(
        schema_version="1.0",
        device_id="22222222-2222-2222-2222-222222222222",
        sent_at="2026-06-16T10:00:00Z",
        events=events,
    )
    assert len(batch.events) == 3


def test_qa_request_day_bounds():
    assert TrackerQARequest(question="what did I do?", days=7).days == 7
    with pytest.raises(ValidationError):
        TrackerQARequest(question="x", days=0)
    with pytest.raises(ValidationError):
        TrackerQARequest(question="x", days=91)
    with pytest.raises(ValidationError):
        TrackerQARequest(question="", days=7)
