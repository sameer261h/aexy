"""Focused tests for pure full-file CSV dry-run preparation."""

import socket

import pytest

from aexy.schemas.csv_import import CsvColumnMapping, CsvImportLimits, CsvPreflightIssue
from aexy.schemas.csv_import_dry_run import CsvDryRunOptions
from aexy.schemas.csv_import_materialization import (
    CsvMaterializationOptions,
    CsvMaterializationTargetAttribute,
    CsvRowMaterializationResult,
)
from aexy.services.csv_import_dry_run_service import CsvImportDryRunService


def _target(
    attribute_id: str,
    attribute_type: str,
    *,
    slug: str | None = None,
    config: dict | None = None,
) -> CsvMaterializationTargetAttribute:
    return CsvMaterializationTargetAttribute(
        id=attribute_id,
        display_name=attribute_id.title(),
        slug=slug or attribute_id,
        attribute_type=attribute_type,
        config=config or {},
    )


def _mapping(*pairs: tuple[str, str]) -> list[CsvColumnMapping]:
    return [CsvColumnMapping(source_header=source, target_attribute_id=target) for source, target in pairs]


def _service() -> CsvImportDryRunService:
    return CsvImportDryRunService()


def _inputs() -> tuple[list[CsvMaterializationTargetAttribute], list[CsvColumnMapping]]:
    return (
        [_target("name", "text"), _target("age", "number")],
        _mapping(("Name", "name"), ("Age", "age")),
    )


def test_valid_file_processes_every_row_and_preserves_orders():
    targets, mapping = _inputs()
    result = _service().dry_run(
        b"Name,Age\nAda,37\nGrace,28\nLin,31\n",
        targets,
        mapping,
        options=CsvDryRunOptions(batch_size=2),
    )

    assert result.dry_run_completed is True
    assert result.total_accepted_data_row_count == 3
    assert result.eligible_row_count == 3
    assert result.rejected_row_count == 0
    assert result.all_rows_valid is True
    assert result.has_executable_rows is True
    assert [row.source_row_number for row in result.prepared_rows] == [2, 3, 4]
    assert list(result.prepared_rows[0].record_values) == ["name", "age"]
    assert [(batch.batch_index, batch.eligible_row_count) for batch in result.batches] == [(0, 2), (1, 1)]


def test_final_batch_and_source_bounds_are_deterministic():
    targets, mapping = _inputs()
    result = _service().dry_run(
        b"Name,Age\nAda,37\nGrace,28\nLin,31\n",
        targets,
        mapping,
        options=CsvDryRunOptions(batch_size=2),
    )

    assert [(batch.first_source_row_number, batch.last_source_row_number) for batch in result.batches] == [
        (2, 3),
        (4, 4),
    ]


@pytest.mark.parametrize("batch_size", [0, -1, 1001])
def test_invalid_or_oversized_batch_size_is_rejected(batch_size):
    with pytest.raises(ValueError):
        CsvDryRunOptions(batch_size=batch_size)


def test_direct_batch_guard_rejects_invalid_size():
    with pytest.raises(ValueError):
        CsvImportDryRunService._make_batches([], 0)


def test_one_invalid_row_does_not_stop_later_rows_and_sets_policy():
    targets, mapping = _inputs()
    result = _service().dry_run(
        b"Name,Age\nAda,37\nGrace,bad\nLin,31\n",
        targets,
        mapping,
    )

    assert result.eligible_row_count == 2
    assert result.rejected_row_count == 1
    assert result.has_mixed_validity is True
    assert result.requires_row_error_policy is True
    assert [row.source_row_number for row in result.prepared_rows] == [2, 4]
    assert [row.source_row_number for batch in result.batches for row in batch.rows] == [2, 4]
    assert result.total_error_count == 1


def test_all_invalid_input_has_no_batches():
    targets, mapping = _inputs()
    result = _service().dry_run(
        b"Name,Age\nAda,bad\nGrace,worse\n",
        targets,
        mapping,
    )

    assert result.eligible_row_count == 0
    assert result.rejected_row_count == 2
    assert result.has_executable_rows is False
    assert result.batches == []
    assert result.all_rows_valid is False


def test_header_only_input_preserves_preflight_warning():
    result = _service().dry_run(b"Name,Age\n", *_inputs())

    assert result.dry_run_completed is True
    assert result.total_accepted_data_row_count == 0
    assert result.eligible_row_count == 0
    assert result.rejected_row_count == 0
    assert result.batches == []
    assert any(issue.code == "HEADER_ONLY_CSV" for issue in result.file_warnings)


@pytest.mark.parametrize("raw_csv", [b"Name\n\xff\n", b'Name\n"unterminated\n'])
def test_file_level_parse_errors_prevent_materialization(raw_csv):
    targets = [_target("name", "text")]
    result = _service().dry_run(raw_csv, targets, _mapping(("Name", "name")))

    assert result.dry_run_completed is False
    assert result.eligible_row_count == 0
    assert result.rejected_row_count == 0
    assert result.prepared_rows == []
    assert result.batches == []
    assert result.row_errors == []


def test_header_or_mapping_error_is_not_repeated_per_row():
    targets = [_target("name", "text")]
    result = _service().dry_run(
        b"Name\nAda\nGrace\n",
        targets,
        _mapping(("Missing", "name")),
    )

    assert result.dry_run_completed is False
    assert [issue.code for issue in result.file_errors] == ["UNKNOWN_SOURCE_COLUMN"]
    assert result.row_errors == []
    assert result.total_error_count == 1


def test_preview_limit_does_not_limit_full_processing():
    targets, mapping = _inputs()
    result = _service().dry_run(
        b"Name,Age\nAda,37\nGrace,28\nLin,31\n",
        targets,
        mapping,
        limits=CsvImportLimits(max_preview_rows=1),
    )

    assert len(result.preflight.preview_rows) == 1
    assert result.total_accepted_data_row_count == 3
    assert result.eligible_row_count == 3


def test_blank_lines_embedded_newlines_and_crlf_keep_preflight_row_numbers():
    targets = [_target("note", "text")]
    mapping = _mapping(("Note", "note"))
    result = _service().dry_run(
        b"Note\r\n\r\n\"first\r\nsecond\"\r\nlast\r\n",
        targets,
        mapping,
    )

    assert [row.source_row_number for row in result.prepared_rows] == [3, 5]


def test_diagnostic_limit_preserves_exact_counts_and_complete_batches():
    targets, mapping = _inputs()
    result = _service().dry_run(
        b"Name,Age\nAda,bad\nGrace,worse\nLin,invalid\n",
        targets,
        mapping,
        options=CsvDryRunOptions(batch_size=2, max_returned_diagnostics=1),
    )

    assert result.diagnostics_truncated is True
    assert len(result.diagnostics) == 1
    assert result.total_error_count == 3
    assert result.total_warning_count >= 1
    assert any(issue.code == "DIAGNOSTICS_TRUNCATED" for issue in result.file_warnings)
    assert result.eligible_row_count == 0
    assert result.batches == []


def test_diagnostic_truncation_does_not_drop_eligible_batches():
    targets, mapping = _inputs()
    result = _service().dry_run(
        b"Name,Age\nAda,37\nGrace,bad\nLin,31\n",
        targets,
        mapping,
        options=CsvDryRunOptions(batch_size=1, max_returned_diagnostics=0),
    )

    assert result.diagnostics_truncated is True
    assert result.diagnostics == []
    assert result.eligible_row_count == 2
    assert [row.source_row_number for batch in result.batches for row in batch.rows] == [2, 4]


def test_materialization_warnings_and_errors_are_aggregated():
    class StubMaterializer:
        def materialize(self, source_row_number, source_cells, mapping, targets, *, options):
            warning = CsvPreflightIssue(
                code="ROW_WARNING", message="warning", row_number=source_row_number
            )
            if source_row_number == 3:
                error = CsvPreflightIssue(
                    code="ROW_ERROR", message="error", row_number=source_row_number
                )
                return CsvRowMaterializationResult(
                    source_row_number=source_row_number,
                    errors=[error],
                    warnings=[warning],
                )
            return CsvRowMaterializationResult(
                source_row_number=source_row_number,
                record_values={"name": source_cells["Name"]},
                warnings=[warning],
                eligible_to_proceed=True,
            )

    result = CsvImportDryRunService(materialization_service=StubMaterializer()).dry_run(
        b"Name\nAda\nGrace\n",
        [_target("name", "text")],
        _mapping(("Name", "name")),
    )

    assert [issue.code for issue in result.row_errors] == ["ROW_ERROR"]
    assert [issue.code for issue in result.row_warnings] == ["ROW_WARNING", "ROW_WARNING"]
    assert result.total_error_count == 1
    assert result.total_warning_count == 2


def test_inputs_are_not_mutated_and_no_network_access_occurs(monkeypatch):
    targets, mapping = _inputs()
    raw_csv = b"Name,Age\nAda,37\n"
    original_targets = [target.model_copy(deep=True) for target in targets]
    original_mapping = [item.model_copy(deep=True) for item in mapping]

    def fail_socket(*args, **kwargs):
        raise AssertionError("dry-run must not create sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    result = _service().dry_run(
        raw_csv,
        targets,
        mapping,
        materialization_options=CsvMaterializationOptions(multi_select_delimiter=","),
    )

    assert result.has_executable_rows is True
    assert targets == original_targets
    assert mapping == original_mapping
    assert raw_csv == b"Name,Age\nAda,37\n"


def test_repeated_identical_input_has_identical_output():
    targets, mapping = _inputs()
    service = _service()
    first = service.dry_run(b"Name,Age\nAda,37\nGrace,28\n", targets, mapping)
    second = service.dry_run(b"Name,Age\nAda,37\nGrace,28\n", targets, mapping)

    assert first.model_dump(mode="python") == second.model_dump(mode="python")
