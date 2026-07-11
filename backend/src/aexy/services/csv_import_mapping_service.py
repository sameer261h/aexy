"""Mapping-completeness validation that sits above the pure preflight
mapping validator (`CsvImportPreflightService._validate_mapping`).

The pure preflight service already rejects unknown/duplicate/non-importable
mappings deterministically -- this module only adds the one check that
requires database-derived authorization context: every required,
authorized attribute must actually receive a mapped source column before a
dry-run may proceed.
"""

from collections.abc import Sequence

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


__all__ = ["validate_required_attributes_mapped"]
