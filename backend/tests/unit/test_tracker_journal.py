"""Unit tests for the deterministic core of the Tracker journal/insight stages.

Covers metric computation, insight thresholds, span metadata carry-over,
date resolution, and journal-prompt truncation — all DB/LLM-free.
"""

from datetime import date, datetime, timezone

from aexy.temporal.activities.tracker_journal import (
    _MAX_JOURNAL_SPANS,
    _compute_metrics,
    _insights_from_metrics,
    _journal_prompt,
    _resolve_date,
    _spans_with_meta,
)


class FakeEvent:
    """Minimal TrackerEvent stand-in for the pure journal/insight helpers."""

    def __init__(self, id, ts, interval_s=600, app="VS Code", category=None,
                 attribution=None, in_call=False):
        self.id = id
        self.ts = ts
        self.interval_s = interval_s
        self.active_app = {"name": app, "window_title": None}
        self.file_context = None
        self.browser = None
        self.dev_context = None
        self.category = category
        self.attribution = attribution
        self.meeting = {"in_call": in_call} if in_call else None


def _ev(id, hour, minute=0, interval_s=600, app="VS Code", category=None,
        in_call=False, attribution=None):
    return FakeEvent(id, datetime(2026, 6, 16, hour, minute, tzinfo=timezone.utc),
                     interval_s=interval_s, app=app, category=category,
                     attribution=attribution, in_call=in_call)


# --------------------------------------------------------------------------- #
# _spans_with_meta
# --------------------------------------------------------------------------- #
def test_spans_with_meta_carries_category_and_attribution():
    events = [
        _ev("a", 10, 0, app="VS Code", category="productive",
            attribution={"task_id": "T1"}),
        _ev("b", 10, 10, app="VS Code", category="productive",
            attribution={"task_id": "T1"}),
    ]
    spans = _spans_with_meta(events)
    assert len(spans) == 1
    assert spans[0]["category"] == "productive"
    assert spans[0]["attribution"]["task_id"] == "T1"


# --------------------------------------------------------------------------- #
# _compute_metrics
# --------------------------------------------------------------------------- #
def test_compute_metrics_full():
    events = [
        _ev("1", 10, 0, app="VS Code", category="productive"),
        _ev("2", 10, 10, app="VS Code", category="productive"),
        _ev("3", 10, 20, app="Chrome", category="neutral"),
        _ev("4", 10, 30, app="Zoom", category="neutral", in_call=True),
        _ev("5", 10, 40, app="Zoom", category="neutral", in_call=True),
        _ev("6", 22, 0, app="VS Code", category="productive"),  # after-hours
    ]
    m = _compute_metrics(events)
    assert m["active_minutes"] == 60.0
    assert m["productive_minutes"] == 30.0
    assert m["meeting_minutes"] == 20.0
    assert m["after_hours_productive"] == 10.0
    # switches: VSCode→Chrome, Chrome→Zoom, Zoom→VSCode = 3 over 1 active hour
    assert m["switches_per_hour"] == 3.0
    # longest unbroken productive span = the two VS Code samples = 20m
    assert m["longest_productive_min"] == 20.0


def test_compute_metrics_empty_uses_floor_for_active_hours():
    # No events → no division by zero (active_hours floored at 0.5).
    m = _compute_metrics([])
    assert m["switches_per_hour"] == 0.0
    assert m["productive_minutes"] == 0.0


# --------------------------------------------------------------------------- #
# _insights_from_metrics
# --------------------------------------------------------------------------- #
_ZERO = {
    "active_minutes": 0.0, "productive_minutes": 0.0, "meeting_minutes": 0.0,
    "after_hours_productive": 0.0, "switches_per_hour": 0.0,
    "longest_productive_min": 0.0,
}


def _types(metrics):
    return {i["type"] for i in _insights_from_metrics(metrics)}


def test_no_insights_when_all_below_threshold():
    assert _types(_ZERO) == set()


def test_context_switching_insight():
    assert "context_switching" in _types({**_ZERO, "switches_per_hour": 20})


def test_meeting_overload_insight():
    m = {**_ZERO, "active_minutes": 400, "meeting_minutes": 240}  # 60% & ≥180m
    assert "meeting_overload" in _types(m)


def test_meeting_overload_not_triggered_below_minute_floor():
    # 60% ratio but only 60 min of meetings — below the absolute floor.
    m = {**_ZERO, "active_minutes": 100, "meeting_minutes": 60}
    assert "meeting_overload" not in _types(m)


def test_after_hours_insight():
    assert "after_hours" in _types({**_ZERO, "after_hours_productive": 120})


def test_fragmented_focus_insight():
    m = {**_ZERO, "productive_minutes": 200, "longest_productive_min": 10}
    assert "fragmented_focus" in _types(m)


def test_fragmented_focus_not_triggered_with_long_span():
    m = {**_ZERO, "productive_minutes": 200, "longest_productive_min": 60}
    assert "fragmented_focus" not in _types(m)


# --------------------------------------------------------------------------- #
# _resolve_date
# --------------------------------------------------------------------------- #
def test_resolve_date_parses_iso():
    assert _resolve_date("2026-06-16") == date(2026, 6, 16)


def test_resolve_date_defaults_to_today():
    assert _resolve_date(None) == datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------- #
# _journal_prompt
# --------------------------------------------------------------------------- #
def test_journal_prompt_truncates_and_notes_omitted_count():
    spans = [
        {"signal": f"app{i}", "duration_s": 60 + i, "category": "neutral",
         "attribution": None}
        for i in range(_MAX_JOURNAL_SPANS + 20)
    ]
    _, user = _journal_prompt(spans)
    assert "shorter spans omitted" in user
    # Only the cap is rendered as detailed lines (+1 omitted-count line).
    assert user.count("\n- ") <= _MAX_JOURNAL_SPANS + 1


def test_journal_prompt_includes_task_when_attributed():
    spans = [{"signal": "VS Code", "duration_s": 600, "category": "productive",
              "attribution": {"task_id": "T9"}}]
    _, user = _journal_prompt(spans)
    assert "task=T9" in user
