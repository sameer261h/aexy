"""Typed contracts for CSV import invalid-row policy, duplicate matching,
row-level dry-run outcomes, and the fully authorized target-attribute shape
used by the upload/preflight/mapping/dry-run API layer.

Builds on the pure `csv_import` and `csv_import_materialization` contracts
without modifying them -- this module only adds the policy/authorization
layer those pure services deliberately do not know about.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aexy.schemas.csv_import import CsvPreflightIssue
from aexy.schemas.csv_import_materialization import CsvMaterializationTargetAttribute

InvalidRowPolicy = Literal["all_or_nothing", "partial"]
DuplicateAction = Literal["skip", "update_existing", "create_anyway"]

DEFAULT_INVALID_ROW_POLICY: InvalidRowPolicy = "all_or_nothing"


class CsvFullTargetAttribute(CsvMaterializationTargetAttribute):
    """Target metadata carrying every field the mapping, materialization,
    relationship-resolution, and duplicate-matching layers need."""

    is_required: bool = False


class CsvImportSchemaResponse(BaseModel):
    """Attributes available for mapping, already filtered to what the
    current user is authorized to see -- hidden, readonly, and
    system-managed attributes are omitted entirely, not merely flagged."""

    attributes: list[CsvFullTargetAttribute] = Field(default_factory=list)


class CsvImportPolicies(BaseModel):
    """Explicit, user-selected dry-run policy. No hidden defaults for
    duplicate handling -- the matching attribute and action are mandatory
    whenever a dry-run is requested."""

    model_config = ConfigDict(frozen=True)

    invalid_row_policy: InvalidRowPolicy = DEFAULT_INVALID_ROW_POLICY
    unique_match_attribute_id: str
    duplicate_action: DuplicateAction


RowOutcomeStatus = Literal["create", "update", "skipped_duplicate", "invalid"]


class CsvRowDryRunOutcome(BaseModel):
    """One logical row's complete dry-run outcome. Never includes a target
    record identifier -- `matched_existing` is the only disclosed signal,
    identical whether the match was found because of an existing record or
    withheld because it was inaccessible would look the same to the caller
    (it wouldn't be reported as matched at all)."""

    source_row_number: int = Field(ge=1)
    status: RowOutcomeStatus
    reason_codes: list[str] = Field(default_factory=list)
    remediation: list[str] = Field(default_factory=list)
    source_values: dict[str, str] = Field(default_factory=dict)
    proposed_values: dict[str, Any] = Field(default_factory=dict)
    matched_existing: bool = False


class CsvImportDryRunSummary(BaseModel):
    """Truthful, server-derived counts suitable for direct frontend
    rendering. Every count is computed from the same row outcomes returned
    in `rows` -- there is no separate, potentially-inconsistent tally."""

    total_logical_data_rows: int = Field(default=0, ge=0)
    valid_row_count: int = Field(default=0, ge=0)
    invalid_row_count: int = Field(default=0, ge=0)
    duplicate_match_count: int = Field(default=0, ge=0)
    create_candidate_count: int = Field(default=0, ge=0)
    update_candidate_count: int = Field(default=0, ge=0)
    skipped_row_count: int = Field(default=0, ge=0)
    execution_blocked: bool = True
    execution_blocked_reason: str | None = None


class CsvImportDryRunPolicyResult(BaseModel):
    """The complete dry-run result: file-level diagnostics, the policies
    used, a truthful summary, and deterministic per-row outcomes. Never
    implies any CRM record was created, updated, or deleted."""

    filename: str | None = None
    dry_run_completed: bool = False
    file_errors: list[CsvPreflightIssue] = Field(default_factory=list)
    file_warnings: list[CsvPreflightIssue] = Field(default_factory=list)
    policies: CsvImportPolicies | None = None
    summary: CsvImportDryRunSummary = Field(default_factory=CsvImportDryRunSummary)
    rows: list[CsvRowDryRunOutcome] = Field(default_factory=list)


__all__ = [
    "CsvFullTargetAttribute",
    "CsvImportSchemaResponse",
    "CsvImportPolicies",
    "CsvImportDryRunPolicyResult",
    "CsvImportDryRunSummary",
    "CsvRowDryRunOutcome",
    "DuplicateAction",
    "InvalidRowPolicy",
    "RowOutcomeStatus",
    "DEFAULT_INVALID_ROW_POLICY",
]
