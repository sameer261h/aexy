"""Typed contracts for pure CSV row materialization."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aexy.schemas.csv_import import (
    CsvColumnMapping,
    CsvImportTargetAttribute,
    CsvPreflightIssue,
)
class CsvMaterializationOptions(BaseModel):
    """Explicit conversion and per-cell safety options for one row."""

    model_config = ConfigDict(frozen=True)

    multi_select_delimiter: str | None = None
    max_cell_length: int = Field(default=100_000, ge=1)


class CsvMaterializationTargetAttribute(CsvImportTargetAttribute):
    """Target metadata plus authoritative type-specific configuration."""

    config: dict[str, Any] = Field(default_factory=dict)


class CsvMaterializedField(BaseModel):
    """The converted value for one mapped target field."""

    source_header: str
    target_attribute_id: str
    target_key: str
    value: Any = None
    conversion_succeeded: bool


class CsvRowMaterializationResult(BaseModel):
    """Diagnostic result for one row, without persistence metadata."""

    source_row_number: int = Field(ge=1)
    record_values: dict[str, Any] = Field(default_factory=dict)
    fields: list[CsvMaterializedField] = Field(default_factory=list)
    errors: list[CsvPreflightIssue] = Field(default_factory=list)
    warnings: list[CsvPreflightIssue] = Field(default_factory=list)
    eligible_to_proceed: bool = False


__all__ = [
    "CsvColumnMapping",
    "CsvMaterializationOptions",
    "CsvMaterializationTargetAttribute",
    "CsvMaterializedField",
    "CsvPreflightIssue",
    "CsvRowMaterializationResult",
]
