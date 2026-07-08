"""Pydantic schemas for CRM pipelines, stages, movement, and lead conversion."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

class StageCreate(BaseModel):
    name: str
    color: str | None = None
    stage_type: str = "open"  # open | won | lost
    probability: int | None = Field(default=None, ge=0, le=100)
    rotting_days: int | None = None


class StageUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    stage_type: str | None = None
    probability: int | None = Field(default=None, ge=0, le=100)
    rotting_days: int | None = None


class StageReorder(BaseModel):
    stage_ids: list[str]


class StageResponse(BaseModel):
    id: str
    pipeline_id: str
    name: str
    value_key: str
    stage_type: str
    position: int
    color: str | None
    probability: int
    rotting_days: int | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Pipelines
# ---------------------------------------------------------------------------

class PipelineCreate(BaseModel):
    object_id: str
    name: str
    description: str | None = None
    is_default: bool = False
    # Adopt an existing STATUS attribute, or omit to create a fresh one.
    adopt_attribute_id: str | None = None
    status_attribute_name: str = "Stage"
    stages: list[StageCreate] | None = None


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None
    is_active: bool | None = None


class PipelineResponse(BaseModel):
    id: str
    workspace_id: str
    object_id: str
    status_attribute_id: str | None
    name: str
    slug: str
    description: str | None
    is_default: bool
    position: int
    is_active: bool
    settings: dict
    created_at: datetime
    updated_at: datetime
    stages: list[StageResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Movement
# ---------------------------------------------------------------------------

class MoveRecord(BaseModel):
    to_stage_key: str


class BulkMove(BaseModel):
    record_ids: list[str]
    to_stage_key: str


# ---------------------------------------------------------------------------
# Lead conversion
# ---------------------------------------------------------------------------

class LeadConvert(BaseModel):
    create_company: bool = True
    create_contact: bool = True
    create_deal: bool = True
    deal_pipeline_id: str | None = None
    deal_stage_key: str | None = None
    field_overrides: dict | None = None
    archive_after_convert: bool = False


class LeadConvertResponse(BaseModel):
    lead_id: str
    company_id: str | None = None
    contact_id: str | None = None
    deal_id: str | None = None


# ---------------------------------------------------------------------------
# Stage history
# ---------------------------------------------------------------------------

class StageHistoryResponse(BaseModel):
    id: str
    record_id: str
    pipeline_id: str | None
    from_stage_key: str | None
    to_stage_key: str
    changed_by_id: str | None
    duration_in_previous_seconds: int | None
    entered_at: datetime

    model_config = ConfigDict(from_attributes=True)
