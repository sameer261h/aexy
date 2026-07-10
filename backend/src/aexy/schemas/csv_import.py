"""Typed, endpoint-independent contracts for CSV import preflight."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CsvImportLimits(BaseModel):
    """Immutable safety limits for one synchronous CSV preflight."""

    model_config = ConfigDict(frozen=True)

    max_file_size_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_data_rows: int = Field(default=10_000, ge=1)
    max_columns: int = Field(default=200, ge=1)
    max_preview_rows: int = Field(default=100, ge=0)
    max_cell_length: int = Field(default=100_000, ge=1)


DEFAULT_CSV_IMPORT_LIMITS = CsvImportLimits()


class CsvImportTargetAttribute(BaseModel):
    """Read-only target metadata supplied by a future API or caller."""

    id: str
    display_name: str
    slug: str | None = None
    attribute_type: str
    importable: bool | None = None


class CsvColumnMapping(BaseModel):
    """One requested source-column to target-attribute mapping."""

    source_header: str
    target_attribute_id: str


class CsvPreflightIssue(BaseModel):
    """A stable, non-sensitive preflight diagnostic."""

    code: str
    message: str
    row_number: int | None = None
    column_number: int | None = None
    source_header: str | None = None
    target_attribute_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class CsvMappingSuggestion(BaseModel):
    """A deterministic, exact-match mapping suggestion."""

    source_header: str
    source_column_number: int
    target_attribute_id: str
    target_display_name: str
    match_reason: Literal["display_name_exact", "slug_exact"]


class CsvPreviewRow(BaseModel):
    """One bounded preview row, retaining the source record's line number."""

    source_row_number: int
    values: list[str]


class CsvImportPreflightResult(BaseModel):
    """The complete deterministic result required before an import can execute."""

    filename: str | None = None
    encoding: str | None = None
    original_headers: list[str] = Field(default_factory=list)
    normalized_headers: list[str] = Field(default_factory=list)
    total_data_row_count: int = 0
    preview_rows: list[CsvPreviewRow] = Field(default_factory=list)
    preview_truncated: bool = False
    mapping_suggestions: list[CsvMappingSuggestion] = Field(default_factory=list)
    validated_mapping: list[CsvColumnMapping] = Field(default_factory=list)
    errors: list[CsvPreflightIssue] = Field(default_factory=list)
    warnings: list[CsvPreflightIssue] = Field(default_factory=list)
    eligible_to_proceed: bool = False
