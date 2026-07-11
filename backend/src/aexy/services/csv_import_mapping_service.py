"""Mapping-completeness validation that sits above the pure preflight
mapping validator (`CsvImportPreflightService._validate_mapping`).

The pure preflight service already rejects unknown/duplicate/non-importable
mappings deterministically -- this module only adds the one check that
requires database-derived authorization context: every required,
authorized attribute must actually receive a mapped source column before a
dry-run may proceed.
"""

from collections.abc import Mapping, Sequence, Set

from aexy.schemas.csv_import import CsvColumnMapping, CsvPreflightIssue
from aexy.schemas.csv_import_policy import CsvFullTargetAttribute


def validate_required_attributes_mapped(
    target_attributes: Sequence[CsvFullTargetAttribute],
    validated_mapping: Sequence[CsvColumnMapping],
) -> list[CsvPreflightIssue]:
    """Every required, authorized, importable attribute must appear in the
    validated mapping. Returns one deterministic issue per missing
    attribute, ordered by attribute id for stable output."""
    mapped_target_ids = {mapping.target_attribute_id for mapping in validated_mapping}
    issues = [
        CsvPreflightIssue(
            code="MISSING_REQUIRED_ATTRIBUTE_MAPPING",
            message=f"Required attribute '{target.display_name}' has no mapped CSV column.",
            target_attribute_id=target.id,
        )
        for target in target_attributes
        if target.is_required and target.importable is not False and target.id not in mapped_target_ids
    ]
    return sorted(issues, key=lambda issue: issue.target_attribute_id or "")


def _is_missing_required_value(value: object) -> bool:
    """Only a true absence of a value counts as missing. Numeric zero and
    boolean false are legitimate values and must never be flagged --
    `False`/`0`/`0.0` all fail `isinstance(value, str | list)` and fall
    through to `False` (not missing) below."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list):
        return len(value) == 0
    return False


def validate_row_required_values(
    target_attributes: Sequence[CsvFullTargetAttribute],
    record_values: Mapping[str, object],
    errored_target_ids: Set[str],
    source_row_number: int,
) -> list[CsvPreflightIssue]:
    """Every required, authorized, importable attribute (already guaranteed
    mapped by `validate_required_attributes_mapped`) must have a
    non-missing materialized value on this specific row. Skips any
    attribute that already produced a materialization/relationship error
    on this row -- that failure already has a more specific reason code,
    and reporting both would be redundant and potentially misleading (the
    value wasn't "missing", it was invalid). Returns one deterministic
    issue per missing attribute, ordered by attribute id for stable
    output."""
    issues = [
        CsvPreflightIssue(
            code="MISSING_REQUIRED_VALUE",
            message=f"Required attribute '{target.display_name}' has no value in this row.",
            row_number=source_row_number,
            target_attribute_id=target.id,
        )
        for target in target_attributes
        if target.is_required
        and target.importable is not False
        and target.id not in errored_target_ids
        and _is_missing_required_value(record_values.get(target.slug or target.id))
    ]
    return sorted(issues, key=lambda issue: issue.target_attribute_id or "")


__all__ = ["validate_required_attributes_mapped", "validate_row_required_values"]
