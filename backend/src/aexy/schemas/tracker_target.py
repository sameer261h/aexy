"""Aexy Tracker — target-hours request/response schemas.

See ``api/tracker_target.py``. Target hours resolve most-specific-first
(developer → project → workspace default → hard fallback).
"""

from pydantic import BaseModel, ConfigDict, Field

# Fallback when no override exists at any level.
DEFAULT_TARGET_HOURS = 8.0


class TargetHoursResolved(BaseModel):
    """Effective daily target for one developer, plus where it came from."""

    target_hours_per_day: float
    # "developer" | "project" | "workspace" | "default"
    source: str


class TargetHoursOverride(BaseModel):
    """One configured override row (admin view)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    project_id: str | None = None
    developer_id: str | None = None
    target_hours_per_day: float
    # Derived: "developer" | "project" | "workspace".
    level: str


class TargetHoursUpsertRequest(BaseModel):
    """Set (create or update) the target at a single level.

    Omit both ``project_id`` and ``developer_id`` for the workspace default;
    set one of them for a project- or developer-level override.
    """

    project_id: str | None = None
    developer_id: str | None = None
    target_hours_per_day: float = Field(gt=0, le=24)
