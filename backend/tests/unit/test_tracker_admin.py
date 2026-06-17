"""Unit tests for Tracker admin config helpers + schemas (no DB/auth).

The endpoint authorization (can_edit_projects / can_view_tracker_records +
same-workspace membership) is integration-tested in CI; these cover the pure
config logic and the capture-config schema validation.
"""

import pytest
from pydantic import ValidationError

from aexy.api.tracker_admin import _apply_project_config, _config_from_settings
from aexy.models.permissions import PERMISSIONS
from aexy.schemas.tracker_ingest import TrackerCaptureConfig


class FakeDevice:
    """Stand-in with just the capture-config columns."""

    def __init__(self):
        self.sample_interval_s = 60
        self.screenshot_policy = "off"
        self.screenshot_every_n_samples = 5
        self.idle_threshold_s = 300
        self.paused = False
        self.excluded_bundle_ids = None


# --------------------------------------------------------------------------- #
# permission registration
# --------------------------------------------------------------------------- #
def test_can_view_tracker_records_permission_registered():
    assert "can_view_tracker_records" in PERMISSIONS
    # Manager/admin get it by default; plain developers do not.
    assert "manager" in PERMISSIONS["can_view_tracker_records"]["default_for"]
    assert "developer" not in PERMISSIONS["can_view_tracker_records"]["default_for"]


# --------------------------------------------------------------------------- #
# _config_from_settings
# --------------------------------------------------------------------------- #
def test_config_from_empty_settings_is_defaults():
    cfg = _config_from_settings(None)
    assert cfg.sample_interval_s == 60
    assert cfg.screenshot_policy == "off"
    assert cfg.excluded_bundle_ids == []


def test_config_from_settings_reads_values():
    cfg = _config_from_settings(
        {"tracker_config": {"sample_interval_s": 120, "screenshot_policy": "active_window"}}
    )
    assert cfg.sample_interval_s == 120
    assert cfg.screenshot_policy == "active_window"


def test_config_from_settings_drops_unknown_keys():
    # Stray/legacy keys must not break parsing (extra="forbid" on the schema).
    cfg = _config_from_settings({"tracker_config": {"sample_interval_s": 90, "bogus": 1}})
    assert cfg.sample_interval_s == 90


# --------------------------------------------------------------------------- #
# _apply_project_config
# --------------------------------------------------------------------------- #
def test_apply_empty_config_leaves_device_defaults():
    d = FakeDevice()
    _apply_project_config(d, {})
    assert d.sample_interval_s == 60 and d.screenshot_policy == "off"


def test_apply_config_sets_only_present_keys():
    d = FakeDevice()
    _apply_project_config(d, {"sample_interval_s": 300, "excluded_bundle_ids": ["com.x"]})
    assert d.sample_interval_s == 300
    assert d.excluded_bundle_ids == ["com.x"]
    assert d.screenshot_policy == "off"  # untouched


# --------------------------------------------------------------------------- #
# TrackerCaptureConfig validation
# --------------------------------------------------------------------------- #
def test_capture_config_rejects_bad_screenshot_policy():
    with pytest.raises(ValidationError):
        TrackerCaptureConfig(screenshot_policy="everything")


@pytest.mark.parametrize("interval", [0, 601, -5])
def test_capture_config_rejects_out_of_range_interval(interval):
    with pytest.raises(ValidationError):
        TrackerCaptureConfig(sample_interval_s=interval)


def test_capture_config_forbids_extra_fields():
    with pytest.raises(ValidationError):
        TrackerCaptureConfig(unknown_field=1)
