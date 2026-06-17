"""Unit tests for the Tracker timesheet review-action decision.

Covers the pure logic of confirm / correct / dismiss (no DB, no auth). The
endpoint (api/tracker_qa.py) wraps this with ownership + is_inferred guards.
"""

import pytest
from fastapi import HTTPException

from aexy.api.tracker_qa import _review_outcome


def test_confirm_keeps_task_and_marks_confirmed():
    task_id, status = _review_outcome("confirm", None, set())
    assert task_id is None  # unchanged
    assert status == "confirmed"


def test_dismiss_keeps_task_and_marks_dismissed():
    task_id, status = _review_outcome("dismiss", None, set())
    assert task_id is None
    assert status == "dismissed"


def test_correct_reassigns_to_valid_task():
    task_id, status = _review_outcome("correct", "T2", {"T1", "T2"})
    assert task_id == "T2"
    assert status == "corrected"


def test_correct_without_task_id_is_400():
    with pytest.raises(HTTPException) as exc:
        _review_outcome("correct", None, {"T1"})
    assert exc.value.status_code == 400


def test_correct_with_unassignable_task_is_400():
    with pytest.raises(HTTPException) as exc:
        _review_outcome("correct", "T9", {"T1", "T2"})
    assert exc.value.status_code == 400


def test_confirm_ignores_candidate_tasks():
    # confirm/dismiss never touch the task, even if a task_id is passed.
    assert _review_outcome("confirm", "T1", set()) == (None, "confirmed")
