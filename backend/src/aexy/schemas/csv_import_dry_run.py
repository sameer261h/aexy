"""Typed contracts for pure CSV import dry-run preparation."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aexy.schemas.csv_import import CsvImportPreflightResult, CsvPreflightIssue


class CsvDryRunOptions(BaseModel):
    """Bounded execution-plan options with no execution policy."""

    model_config = ConfigDict(frozen=True)

    batch_size: int = Field(default=100, ge=1, le=1000)
    max_returned_diagnostics: int = Field(default=1000, ge=0)


class CsvPreparedRow(BaseModel):
    """Candidate values for one eligible source row, before persistence."""

    source_row_number: int = Field(ge=1)
    record_values: dict[str, Any] = Field(default_factory=dict)
    warnings: list[CsvPreflightIssue] = Field(default_factory=list)


class CsvDryRunBatch(BaseModel):
    """Deterministic execution plan batch; no execution has occurred."""

    batch_index: int = Field(ge=0)
    eligible_row_count: int = Field(ge=1)
    rows: list[CsvPreparedRow] = Field(min_length=1)
    first_source_row_number: int = Field(ge=1)
    last_source_row_number: int = Field(ge=1)


class CsvImportDryRunResult(BaseModel):
    """Complete pure dry-run result, explicitly distinct from import success."""

    filename: str | None = None
    preflight: CsvImportPreflightResult
    dry_run_completed: bool = False
    total_accepted_data_row_count: int = Field(default=0, ge=0)
    eligible_row_count: int = Field(default=0, ge=0)
    rejected_row_count: int = Field(default=0, ge=0)
    all_rows_valid: bool = True
    has_executable_rows: bool = False
    has_mixed_validity: bool = False
    requires_row_error_policy: bool = False
    prepared_rows: list[CsvPreparedRow] = Field(default_factory=list)
    batches: list[CsvDryRunBatch] = Field(default_factory=list)
    diagnostics: list[CsvPreflightIssue] = Field(default_factory=list)
    total_error_count: int = Field(default=0, ge=0)
    total_warning_count: int = Field(default=0, ge=0)
    diagnostics_truncated: bool = False
    file_errors: list[CsvPreflightIssue] = Field(default_factory=list)
    file_warnings: list[CsvPreflightIssue] = Field(default_factory=list)
    row_errors: list[CsvPreflightIssue] = Field(default_factory=list)
    row_warnings: list[CsvPreflightIssue] = Field(default_factory=list)


__all__ = [
    "CsvDryRunBatch",
    "CsvDryRunOptions",
    "CsvImportDryRunResult",
    "CsvPreparedRow",
]
