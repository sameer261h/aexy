"""Relationship-column resolution for CSV import dry-run.

The pure `CsvImportMaterializationService` deliberately treats
`record_reference` as an unsupported attribute type (no database access is
available to it). This module adds that support as a thin, additive layer:
it batch-resolves CSV cell values mapped to `record_reference` attributes
using the exact same authorized, non-disclosing resolver the Related-tab
read path already uses (`CRMRelationshipService._resolve_target_ids`) --
no parallel authorization or relationship-lookup logic is introduced.

Convention: a `record_reference` CSV cell holds the target record's own ID
(the same plain-UUID representation `CRMRecord.values[slug]` already
stores), or a delimiter-separated list of IDs for `allowMultiple`
attributes. Label-based lookup is out of scope for this slice -- see the
handoff's known-limitations section.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from aexy.schemas.csv_import import CsvColumnMapping, CsvPreflightIssue
from aexy.schemas.csv_import_policy import CsvFullTargetAttribute
from aexy.services.crm_relationship_service import CRMRelationshipService

RECORD_REFERENCE_TYPE = "record_reference"
DEFAULT_RELATIONSHIP_DELIMITER = "|"


@dataclass
class RelationshipCellOutcome:
    target_key: str
    value: list[str] | None = None
    conversion_succeeded: bool = False
    errors: list[CsvPreflightIssue] = field(default_factory=list)


class CsvImportRelationshipService:
    """Resolve every mapped `record_reference` cell across a whole CSV in
    batched, per-target-object queries -- never one query per row."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._relationships = CRMRelationshipService(db)

    @staticmethod
    def split_relationship_mapping(
        mapping: Sequence[CsvColumnMapping],
        target_attributes: Sequence[CsvFullTargetAttribute],
    ) -> tuple[list[CsvColumnMapping], list[CsvColumnMapping]]:
        """Split a validated mapping into (scalar_mapping, relationship_mapping)."""
        targets_by_id = {target.id: target for target in target_attributes}
        scalar: list[CsvColumnMapping] = []
        relationship: list[CsvColumnMapping] = []
        for entry in mapping:
            target = targets_by_id.get(entry.target_attribute_id)
            if target is not None and target.attribute_type == RECORD_REFERENCE_TYPE:
                relationship.append(entry)
            else:
                scalar.append(entry)
        return scalar, relationship

    async def resolve_rows(
        self,
        rows: Sequence[tuple[int, Mapping[str, str]]],
        relationship_mapping: Sequence[CsvColumnMapping],
        target_attributes: Sequence[CsvFullTargetAttribute],
        workspace_id: str,
        user_id: str,
        *,
        delimiter: str = DEFAULT_RELATIONSHIP_DELIMITER,
    ) -> dict[int, dict[str, RelationshipCellOutcome]]:
        """Resolve every relationship-mapped cell for every row in one pass.

        Returns `{source_row_number: {target_attribute_id: outcome}}`.
        """
        if not relationship_mapping:
            return {}

        targets_by_id = {target.id: target for target in target_attributes}

        # Pass 1: collect every requested ID per target object across all
        # rows so resolution is one batched query per target object, not
        # one query per row.
        requested_ids_by_object: dict[str, set[str]] = {}
        parsed_by_row_and_mapping: dict[int, dict[str, list[str]]] = {}
        for source_row_number, source_cells in rows:
            parsed_by_row_and_mapping[source_row_number] = {}
            for entry in relationship_mapping:
                target = targets_by_id.get(entry.target_attribute_id)
                if target is None:
                    continue
                raw_value = source_cells.get(entry.source_header, "")
                ids = self._parse_ids(raw_value, delimiter)
                parsed_by_row_and_mapping[source_row_number][entry.target_attribute_id] = ids
                target_object_id = target.config.get("targetObjectId")
                if target_object_id and ids:
                    requested_ids_by_object.setdefault(target_object_id, set()).update(ids)

        resolved_by_object: dict[str, dict[str, dict[str, Any] | None]] = {}
        for target_object_id, object_ids in requested_ids_by_object.items():
            resolved_by_object[target_object_id] = await self._relationships._resolve_target_ids(
                target_object_id, list(object_ids), workspace_id, user_id,
            )

        # Pass 2: build per-row, per-attribute outcomes from the batched results.
        outcomes: dict[int, dict[str, RelationshipCellOutcome]] = {}
        for source_row_number, parsed in parsed_by_row_and_mapping.items():
            row_outcomes: dict[str, RelationshipCellOutcome] = {}
            for entry in relationship_mapping:
                target = targets_by_id.get(entry.target_attribute_id)
                if target is None:
                    row_outcomes[entry.target_attribute_id] = RelationshipCellOutcome(
                        target_key=entry.target_attribute_id,
                        errors=[CsvPreflightIssue(
                            code="UNKNOWN_TARGET_ATTRIBUTE",
                            message="Mapping references target metadata that was not supplied.",
                            source_header=entry.source_header,
                            target_attribute_id=entry.target_attribute_id,
                        )],
                    )
                    continue
                target_key = target.slug or target.id
                ids = parsed.get(entry.target_attribute_id, [])
                allow_multiple = bool(target.config.get("allowMultiple"))
                row_outcomes[entry.target_attribute_id] = self._build_outcome(
                    ids, target, target_key, allow_multiple, entry,
                    resolved_by_object.get(target.config.get("targetObjectId", ""), {}),
                )
            outcomes[source_row_number] = row_outcomes
        return outcomes

    @staticmethod
    def _parse_ids(raw_value: str, delimiter: str) -> list[str]:
        if raw_value == "":
            return []
        return [token.strip() for token in raw_value.split(delimiter) if token.strip()]

    @staticmethod
    def _build_outcome(
        ids: list[str],
        target: CsvFullTargetAttribute,
        target_key: str,
        allow_multiple: bool,
        mapping_entry: CsvColumnMapping,
        resolved: dict[str, dict[str, Any] | None],
    ) -> RelationshipCellOutcome:
        if not ids:
            return RelationshipCellOutcome(target_key=target_key, value=[], conversion_succeeded=True)
        if not allow_multiple and len(ids) > 1:
            return RelationshipCellOutcome(
                target_key=target_key,
                errors=[CsvPreflightIssue(
                    code="RELATIONSHIP_CARDINALITY_EXCEEDED",
                    message="Single-value relationship column received multiple identifiers.",
                    source_header=mapping_entry.source_header,
                    target_attribute_id=target.id,
                )],
            )
        # Non-disclosing: any unresolved ID (unknown, foreign-workspace,
        # row-security-excluded) produces one generic error -- never
        # distinguishing which case applied.
        if any(resolved.get(identifier) is None for identifier in ids):
            return RelationshipCellOutcome(
                target_key=target_key,
                errors=[CsvPreflightIssue(
                    code="INVALID_RELATIONSHIP_REFERENCE",
                    message="One or more referenced records are invalid or inaccessible.",
                    source_header=mapping_entry.source_header,
                    target_attribute_id=target.id,
                )],
            )
        # Always the resolved ID list, in requested order; the orchestrator
        # collapses to a scalar for single-cardinality attributes when it
        # writes the final `record_values` entry.
        return RelationshipCellOutcome(
            target_key=target_key,
            value=list(ids),
            conversion_succeeded=True,
        )


__all__ = ["CsvImportRelationshipService", "RelationshipCellOutcome", "RECORD_REFERENCE_TYPE"]
