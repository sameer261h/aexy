"""The policy-aware CSV import dry-run orchestrator.

Reuses the pure preflight parser (`CsvImportPreflightService`), the pure
scalar-field converter (`CsvImportMaterializationService`), and the
authorized relationship resolver (`CsvImportRelationshipService`) to
process every logical row, then applies duplicate matching
(`CsvImportDuplicateService`) and the caller-selected invalid-row /
duplicate-action policies to produce one truthful, deterministic result.

Never creates, updates, or deletes a CRM record. Every database access in
this module is a read.
"""

from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession
from aexy.schemas.csv_import import (
    CsvColumnMapping,
    CsvImportLimits,
    CsvImportTargetAttribute,
    CsvPreflightIssue,
    DEFAULT_CSV_IMPORT_LIMITS,
)
from aexy.schemas.csv_import_materialization import (
    CsvMaterializationOptions,
    CsvMaterializationTargetAttribute,
)
from aexy.schemas.csv_import_policy import (
    CsvFullTargetAttribute,
    CsvImportDryRunPolicyResult,
    CsvImportDryRunSummary,
    CsvImportPolicies,
    CsvRowDryRunOutcome,
    RowOutcomeStatus,
)
from aexy.services.csv_import_duplicate_service import CsvImportDuplicateService
from aexy.services.csv_import_mapping_service import (
    validate_required_attributes_mapped,
    validate_row_required_values,
)
from aexy.services.csv_import_materialization_service import CsvImportMaterializationService
from aexy.services.csv_import_preflight_service import CsvImportPreflightService
from aexy.services.csv_import_relationship_service import CsvImportRelationshipService

MULTI_VALUE_RELATIONSHIP_DELIMITER = "|"
MULTI_SELECT_DELIMITER = "|"


class CsvImportPolicyService:
    """Coordinates the fully policy-aware dry-run for one CSV upload."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._preflight = CsvImportPreflightService()
        self._materialization = CsvImportMaterializationService()
        self._relationships = CsvImportRelationshipService(db)
        self._duplicates = CsvImportDuplicateService(db)

    async def dry_run(
        self,
        raw_csv: bytes,
        target_attributes: Sequence[CsvFullTargetAttribute],
        proposed_mapping: Sequence[CsvColumnMapping],
        policies: CsvImportPolicies,
        *,
        object_id: str,
        workspace_id: str,
        user_id: str,
        filename: str | None = None,
        limits: CsvImportLimits = DEFAULT_CSV_IMPORT_LIMITS,
    ) -> CsvImportDryRunPolicyResult:
        preflight_targets = [
            CsvImportTargetAttribute.model_validate(t.model_dump(mode="python"))
            for t in target_attributes
        ]
        preflight_result, accepted_rows = self._preflight.preflight_with_rows(
            raw_csv, preflight_targets, proposed_mapping, filename=filename, limits=limits,
        )

        if preflight_result.errors:
            return CsvImportDryRunPolicyResult(
                filename=filename,
                dry_run_completed=False,
                file_errors=list(preflight_result.errors),
                file_warnings=list(preflight_result.warnings),
                policies=policies,
                summary=CsvImportDryRunSummary(execution_blocked=True, execution_blocked_reason="File-level validation failed."),
            )

        validated_mapping = preflight_result.validated_mapping
        targets_by_id = {t.id: t for t in target_attributes}

        required_issues = validate_required_attributes_mapped(target_attributes, validated_mapping)
        unique_target = targets_by_id.get(policies.unique_match_attribute_id)
        file_errors = list(required_issues)
        if unique_target is None:
            file_errors.append(CsvPreflightIssue(
                code="UNKNOWN_UNIQUE_MATCH_ATTRIBUTE",
                message="The selected unique matching attribute is not an authorized target attribute.",
                target_attribute_id=policies.unique_match_attribute_id,
            ))
        elif policies.unique_match_attribute_id not in {m.target_attribute_id for m in validated_mapping}:
            file_errors.append(CsvPreflightIssue(
                code="UNIQUE_MATCH_ATTRIBUTE_NOT_MAPPED",
                message="The selected unique matching attribute has no mapped CSV column.",
                target_attribute_id=policies.unique_match_attribute_id,
            ))

        if file_errors:
            return CsvImportDryRunPolicyResult(
                filename=filename,
                dry_run_completed=False,
                file_errors=file_errors,
                file_warnings=list(preflight_result.warnings),
                policies=policies,
                summary=CsvImportDryRunSummary(execution_blocked=True, execution_blocked_reason="Mapping is incomplete."),
            )

        # unique_target is guaranteed non-None here: the only path that
        # leaves it None also appends to file_errors above, which returns.
        assert unique_target is not None

        scalar_mapping, relationship_mapping = CsvImportRelationshipService.split_relationship_mapping(
            validated_mapping, target_attributes,
        )
        headers = preflight_result.original_headers
        materialization_targets = [
            self._to_materialization_target(t) for t in target_attributes
        ]

        rows_as_cells: list[tuple[int, dict[str, str]]] = [
            (row_number, dict(zip(headers, values, strict=True)))
            for row_number, values in accepted_rows
        ]

        relationship_outcomes = await self._relationships.resolve_rows(
            rows_as_cells, relationship_mapping, target_attributes, workspace_id, user_id,
            delimiter=MULTI_VALUE_RELATIONSHIP_DELIMITER,
        )

        mapped_headers = {m.source_header for m in validated_mapping}
        unique_target_key = unique_target.slug or unique_target.id

        row_states: list[dict[str, Any]] = []
        candidate_unique_values: list[str] = []
        for source_row_number, source_cells in rows_as_cells:
            materialized = self._materialization.materialize(
                source_row_number, source_cells, scalar_mapping, materialization_targets,
                options=CsvMaterializationOptions(
                    multi_select_delimiter=MULTI_SELECT_DELIMITER, max_cell_length=limits.max_cell_length,
                ),
            )
            record_values = dict(materialized.record_values)
            errors = list(materialized.errors)
            warnings = list(materialized.warnings)

            for entry in relationship_mapping:
                outcome = relationship_outcomes.get(source_row_number, {}).get(entry.target_attribute_id)
                if outcome is None:
                    continue
                target = targets_by_id[entry.target_attribute_id]
                errors.extend(outcome.errors)
                if outcome.conversion_succeeded and outcome.value is not None:
                    allow_multiple = bool(target.config.get("allowMultiple"))
                    key = target.slug or target.id
                    record_values[key] = outcome.value if allow_multiple else (
                        outcome.value[0] if outcome.value else None
                    )

            errored_target_ids = {issue.target_attribute_id for issue in errors if issue.target_attribute_id}
            errors.extend(validate_row_required_values(
                target_attributes, record_values, errored_target_ids, source_row_number,
            ))

            source_values = {
                header: value
                for header, value in source_cells.items()
                if header in mapped_headers
            }
            row_states.append({
                "source_row_number": source_row_number,
                "record_values": record_values,
                "errors": errors,
                "warnings": warnings,
                "source_values": source_values,
            })
            if not errors:
                candidate_value = record_values.get(unique_target_key)
                if candidate_value is not None and not isinstance(candidate_value, list):
                    candidate_unique_values.append(str(candidate_value))

        match_results = await self._duplicates.match_existing_records(
            object_id, workspace_id, user_id, unique_target_key, candidate_unique_values,
        )

        outcomes: list[CsvRowDryRunOutcome] = []
        valid_count = invalid_count = duplicate_count = create_count = update_count = skipped_count = 0
        for state in row_states:
            if state["errors"]:
                invalid_count += 1
                outcomes.append(CsvRowDryRunOutcome(
                    source_row_number=state["source_row_number"],
                    status="invalid",
                    reason_codes=[issue.code for issue in state["errors"]],
                    remediation=[issue.message for issue in state["errors"]],
                    source_values=state["source_values"],
                    proposed_values=state["record_values"],
                    matched_existing=False,
                ))
                continue

            candidate_value = state["record_values"].get(unique_target_key)
            match_status: Literal["none", "match", "ambiguous"] = "none"
            if candidate_value is not None and not isinstance(candidate_value, list):
                match_status = match_results.get(str(candidate_value), "none")

            if match_status == "ambiguous":
                invalid_count += 1
                outcomes.append(CsvRowDryRunOutcome(
                    source_row_number=state["source_row_number"],
                    status="invalid",
                    reason_codes=["AMBIGUOUS_DUPLICATE_MATCH"],
                    remediation=[
                        "The selected matching value corresponds to multiple accessible "
                        "records and must be resolved before importing."
                    ],
                    source_values=state["source_values"],
                    proposed_values=state["record_values"],
                    matched_existing=False,
                ))
                continue

            valid_count += 1
            matched = match_status == "match"
            row_status: RowOutcomeStatus
            if matched:
                duplicate_count += 1
                if policies.duplicate_action == "skip":
                    skipped_count += 1
                    row_status = "skipped_duplicate"
                elif policies.duplicate_action == "update_existing":
                    update_count += 1
                    row_status = "update"
                else:
                    create_count += 1
                    row_status = "create"
            else:
                create_count += 1
                row_status = "create"

            outcomes.append(CsvRowDryRunOutcome(
                source_row_number=state["source_row_number"],
                status=row_status,
                reason_codes=[issue.code for issue in state["warnings"]],
                remediation=[issue.message for issue in state["warnings"]],
                source_values=state["source_values"],
                proposed_values=state["record_values"],
                matched_existing=matched,
            ))

        if policies.invalid_row_policy == "all_or_nothing":
            execution_blocked = invalid_count > 0
            reason = (
                "The all_or_nothing policy blocks execution while any invalid row exists."
                if execution_blocked else None
            )
        else:
            execution_blocked = valid_count == 0
            reason = "No valid rows are available to execute." if execution_blocked else None

        summary = CsvImportDryRunSummary(
            total_logical_data_rows=len(row_states),
            valid_row_count=valid_count,
            invalid_row_count=invalid_count,
            duplicate_match_count=duplicate_count,
            create_candidate_count=create_count,
            update_candidate_count=update_count,
            skipped_row_count=skipped_count,
            execution_blocked=execution_blocked,
            execution_blocked_reason=reason,
        )

        return CsvImportDryRunPolicyResult(
            filename=filename,
            dry_run_completed=True,
            file_errors=[],
            file_warnings=list(preflight_result.warnings),
            policies=policies,
            summary=summary,
            rows=outcomes,
        )

    @staticmethod
    def _to_materialization_target(target: CsvFullTargetAttribute) -> CsvMaterializationTargetAttribute:
        return CsvMaterializationTargetAttribute.model_validate(target.model_dump(mode="python"))


__all__ = ["CsvImportPolicyService"]
