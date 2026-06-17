"""Unit tests for the deterministic core of the Tracker enrich/attribute stage.

These cover the pure logic (no DB, no LLM): signal rendering, span collapsing,
LLM-response JSON parsing, and prompt assembly.
"""

from datetime import datetime, timezone

import pytest

from aexy.temporal.activities.tracker_enrich import (
    _build_prompt,
    _collapse_spans,
    _parse_llm_json,
    _signal_text,
)


class FakeEvent:
    """Minimal stand-in for TrackerEvent with just the attributes the pure
    helpers read."""

    def __init__(
        self,
        id,
        ts,
        interval_s=60,
        app="VS Code",
        title=None,
        repo=None,
        branch=None,
        url=None,
        command=None,
        category=None,
        attribution=None,
    ):
        self.id = id
        self.ts = ts
        self.interval_s = interval_s
        self.active_app = {"name": app, "window_title": title}
        self.file_context = {"repo": repo, "branch": branch} if (repo or branch) else None
        self.browser = {"url": url} if url else None
        self.dev_context = {"last_command": command} if command else None
        self.category = category
        self.attribution = attribution


def _ts(hour, minute=0):
    return datetime(2026, 6, 16, hour, minute, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# _signal_text
# --------------------------------------------------------------------------- #
def test_signal_text_includes_all_present_signals():
    e = FakeEvent(
        "1", _ts(10), app="VS Code", title="main.py",
        repo="aexy", branch="dev", url="https://x.com", command="pytest",
    )
    sig = _signal_text(e)
    assert "VS Code" in sig
    assert '"main.py"' in sig
    assert "repo=aexy@dev" in sig
    assert "url=https://x.com" in sig
    assert "$ pytest" in sig


def test_signal_text_minimal_is_just_app():
    assert _signal_text(FakeEvent("1", _ts(10), app="Slack")) == "Slack"


# --------------------------------------------------------------------------- #
# _collapse_spans
# --------------------------------------------------------------------------- #
def test_collapse_merges_consecutive_identical_signals():
    events = [
        FakeEvent("a", _ts(10, 0), interval_s=60, app="VS Code"),
        FakeEvent("b", _ts(10, 1), interval_s=60, app="VS Code"),
        FakeEvent("c", _ts(10, 2), interval_s=60, app="VS Code"),
    ]
    spans = _collapse_spans(events)
    assert len(spans) == 1
    assert spans[0]["event_ids"] == ["a", "b", "c"]
    assert spans[0]["duration_s"] == 180
    assert spans[0]["start"] == _ts(10, 0)
    assert spans[0]["end"] == _ts(10, 2)


def test_collapse_splits_on_signal_change():
    events = [
        FakeEvent("a", _ts(10, 0), app="VS Code"),
        FakeEvent("b", _ts(10, 1), app="Chrome"),
        FakeEvent("c", _ts(10, 2), app="VS Code"),
    ]
    spans = _collapse_spans(events)
    assert [s["signal"] for s in spans] == ["VS Code", "Chrome", "VS Code"]
    assert all(s["duration_s"] == 60 for s in spans)


def test_collapse_sorts_by_ts_before_grouping():
    events = [
        FakeEvent("late", _ts(10, 2), app="VS Code"),
        FakeEvent("early", _ts(10, 0), app="VS Code"),
        FakeEvent("mid", _ts(10, 1), app="VS Code"),
    ]
    spans = _collapse_spans(events)
    assert len(spans) == 1
    assert spans[0]["event_ids"] == ["early", "mid", "late"]


def test_collapse_empty():
    assert _collapse_spans([]) == []


# --------------------------------------------------------------------------- #
# _parse_llm_json
# --------------------------------------------------------------------------- #
def test_parse_plain_json():
    out = _parse_llm_json('{"spans": [{"index": 0, "category": "productive"}]}')
    assert out["spans"][0]["category"] == "productive"


def test_parse_fenced_json():
    out = _parse_llm_json('```json\n{"spans": []}\n```')
    assert out == {"spans": []}


def test_parse_json_with_surrounding_prose():
    out = _parse_llm_json('Sure! Here it is: {"spans": [{"index": 1}]} — done.')
    assert out["spans"][0]["index"] == 1


def test_parse_raises_when_no_json():
    with pytest.raises(ValueError):
        _parse_llm_json("there is no json here")


# --------------------------------------------------------------------------- #
# _build_prompt
# --------------------------------------------------------------------------- #
def test_build_prompt_lists_spans_and_tasks():
    spans = [
        {"signal": "VS Code", "duration_s": 120},
        {"signal": "Chrome", "duration_s": 60},
    ]
    tasks = [{"id": "T1", "title": "Fix auth", "status": "in_progress"}]
    system, user = _build_prompt(spans, tasks)
    assert "JSON" in system
    assert "[0]" in user and "[1]" in user
    assert "T1: Fix auth" in user


def test_build_prompt_handles_no_candidate_tasks():
    _, user = _build_prompt([{"signal": "VS Code", "duration_s": 60}], [])
    assert "(none)" in user
