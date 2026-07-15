"""Unit tests for Tracker admin config helpers + schemas (no DB/auth).

The endpoint authorization (can_edit_projects / can_view_tracker_records +
same-workspace membership) is integration-tested in CI; these cover the pure
config logic and the capture-config schema validation.
"""

import pytest
from pydantic import ValidationError

from aexy.api.tracker_admin import _apply_config_to_device, _config_from_settings
from aexy.models.permissions import PERMISSIONS
from aexy.schemas.tracker_ingest import TrackerCaptureConfig


class FakeDevice:
    """Stand-in with just the capture-config columns + etag."""

    def __init__(self):
        self.sample_interval_s = 60
        self.screenshot_policy = "off"
        self.screenshot_every_n_samples = 5
        self.idle_threshold_s = 300
        self.paused = False
        self.excluded_bundle_ids = None
        self.config_etag = None


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
# _apply_config_to_device
# --------------------------------------------------------------------------- #
def test_apply_config_writes_every_field_and_etag():
    d = FakeDevice()
    cfg = TrackerCaptureConfig(sample_interval_s=300, excluded_bundle_ids=["com.x"])
    _apply_config_to_device(d, cfg, "cfg_abc123")
    assert d.sample_interval_s == 300
    assert d.excluded_bundle_ids == ["com.x"]
    assert d.config_etag == "cfg_abc123"


def test_apply_config_resets_unspecified_fields_to_schema_defaults():
    # The full validated config is applied, so a field the caller didn't set is
    # written from the schema default (not left at the device's prior value).
    d = FakeDevice()
    d.screenshot_policy = "active_window"  # stale prior value
    cfg = TrackerCaptureConfig(sample_interval_s=120)  # screenshot_policy defaults to "off"
    _apply_config_to_device(d, cfg, "cfg_def456")
    assert d.sample_interval_s == 120
    assert d.screenshot_policy == "off"


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
