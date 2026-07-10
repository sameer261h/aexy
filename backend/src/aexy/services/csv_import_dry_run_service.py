"""Pure full-file CSV dry-run and deterministic batch preparation."""

from collections.abc import Sequence
from typing import Any

from aexy.schemas.csv_import import (
    CsvColumnMapping,
    DEFAULT_CSV_IMPORT_LIMITS,
    CsvImportLimits,
    CsvImportTargetAttribute,
    CsvPreflightIssue,
)
from aexy.schemas.csv_import_dry_run import (
    CsvDryRunBatch,
    CsvDryRunOptions,
    CsvImportDryRunResult,
    CsvPreparedRow,
)
from aexy.schemas.csv_import_materialization import (
    CsvMaterializationOptions,
    CsvMaterializationTargetAttribute,
)
from aexy.services.csv_import_materialization_service import (
    CsvImportMaterializationService,
)
from aexy.services.csv_import_preflight_service import CsvImportPreflightService


class CsvImportDryRunService:
    """Coordinate preflight and row materialization without side effects."""

    def __init__(
        self,
        *,
        preflight_service: CsvImportPreflightService | None = None,
        materialization_service: CsvImportMaterializationService | None = None,
    ) -> None:
        self._preflight = preflight_service or CsvImportPreflightService()
        self._materialization = materialization_service or CsvImportMaterializationService()

    def dry_run(
        self,
        raw_csv: bytes,
        target_attributes: Sequence[
            CsvMaterializationTargetAttribute | CsvImportTargetAttribute
        ],
        proposed_mapping: Sequence[CsvColumnMapping] | None = None,
        *,
        filename: str | None = None,
        limits: CsvImportLimits = DEFAULT_CSV_IMPORT_LIMITS,
        materialization_options: CsvMaterializationOptions | None = None,
        options: CsvDryRunOptions | None = None,
    ) -> CsvImportDryRunResult:
        """Run a complete pure dry-run and prepare eligible rows in batches."""
        dry_run_options = options or CsvDryRunOptions()
        materialization_options = materialization_options or CsvMaterializationOptions(
            max_cell_length=limits.max_cell_length
        )
        materialization_targets = self._copy_targets(target_attributes)
        preflight_targets = [
            CsvImportTargetAttribute.model_validate(target.model_dump(mode="python"))
            for target in materialization_targets
        ]
        preflight_result, accepted_rows = self._preflight.preflight_with_rows(
            raw_csv,
            preflight_targets,
            proposed_mapping,
            filename=filename,
            limits=limits,
        )
        file_errors = list(preflight_result.errors)
        file_warnings = list(preflight_result.warnings)
        if file_errors:
            return self._result(
                filename,
                preflight_result,
                file_errors=file_errors,
                file_warnings=file_warnings,
                options=dry_run_options,
            )

        headers = preflight_result.original_headers
        mapping = preflight_result.validated_mapping
        row_errors: list[CsvPreflightIssue] = []
        row_warnings: list[CsvPreflightIssue] = []
        prepared_rows: list[CsvPreparedRow] = []
        for source_row_number, values in accepted_rows:
            source_cells = dict(zip(headers, values, strict=True))
            materialized = self._materialization.materialize(
                source_row_number,
                source_cells,
                mapping,
                materialization_targets,
                options=materialization_options,
            )
            row_errors.extend(materialized.errors)
            row_warnings.extend(materialized.warnings)
            if materialized.eligible_to_proceed:
                prepared_rows.append(
                    CsvPreparedRow(
                        source_row_number=source_row_number,
                        record_values=dict(materialized.record_values),
                        warnings=list(materialized.warnings),
                    )
                )

        batches = self._make_batches(prepared_rows, dry_run_options.batch_size)
        return self._result(
            filename,
            preflight_result,
            file_errors=file_errors,
            file_warnings=file_warnings,
            row_errors=row_errors,
            row_warnings=row_warnings,
            prepared_rows=prepared_rows,
            batches=batches,
            options=dry_run_options,
        )

    @staticmethod
    def _copy_targets(
        targets: Sequence[CsvMaterializationTargetAttribute | CsvImportTargetAttribute],
    ) -> list[CsvMaterializationTargetAttribute]:
        return [
            CsvMaterializationTargetAttribute.model_validate(
                target.model_dump(mode="python")
            )
            for target in targets
        ]

    @staticmethod
    def _make_batches(rows: Sequence[CsvPreparedRow], batch_size: int) -> list[CsvDryRunBatch]:
        if not 1 <= batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")
        return [
            CsvDryRunBatch(
                batch_index=index,
                eligible_row_count=len(chunk),
                rows=list(chunk),
                first_source_row_number=chunk[0].source_row_number,
                last_source_row_number=chunk[-1].source_row_number,
            )
            for index, start in enumerate(range(0, len(rows), batch_size))
            if (chunk := rows[start : start + batch_size])
        ]

    @staticmethod
    def _result(
        filename: str | None,
        preflight: Any,
        *,
        file_errors: list[CsvPreflightIssue],
        file_warnings: list[CsvPreflightIssue],
        row_errors: list[CsvPreflightIssue] | None = None,
        row_warnings: list[CsvPreflightIssue] | None = None,
        prepared_rows: list[CsvPreparedRow] | None = None,
        batches: list[CsvDryRunBatch] | None = None,
        options: CsvDryRunOptions,
    ) -> CsvImportDryRunResult:
        row_errors = row_errors or []
        row_warnings = row_warnings or []
        prepared_rows = prepared_rows or []
        batches = batches or []
        total_rows = preflight.total_data_row_count
        eligible_count = len(prepared_rows)
        rejected_count = total_rows - eligible_count if not file_errors else 0
        all_rows_valid = rejected_count == 0
        mixed = eligible_count > 0 and rejected_count > 0
        diagnostics_source = [*row_errors, *row_warnings]
        diagnostics = diagnostics_source[: options.max_returned_diagnostics]
        truncated = len(diagnostics) < len(diagnostics_source)
        if truncated:
            file_warnings = [
                *file_warnings,
                CsvPreflightIssue(
                    code="DIAGNOSTICS_TRUNCATED",
                    message="Returned row diagnostics were bounded; aggregate counts remain exact.",
                    context={"limit": options.max_returned_diagnostics},
                ),
            ]
        total_errors = len(file_errors) + len(row_errors)
        total_warnings = len(file_warnings) + len(row_warnings)
        return CsvImportDryRunResult(
            filename=filename,
            preflight=preflight,
            dry_run_completed=not bool(file_errors),
            total_accepted_data_row_count=total_rows,
            eligible_row_count=eligible_count,
            rejected_row_count=rejected_count,
            all_rows_valid=all_rows_valid,
            has_executable_rows=eligible_count > 0,
            has_mixed_validity=mixed,
            requires_row_error_policy=mixed,
            prepared_rows=prepared_rows,
            batches=batches,
            diagnostics=diagnostics,
            total_error_count=total_errors,
            total_warning_count=total_warnings,
            diagnostics_truncated=truncated,
            file_errors=file_errors,
            file_warnings=file_warnings,
            row_errors=row_errors,
            row_warnings=row_warnings,
        )


__all__ = ["CsvImportDryRunService"]
