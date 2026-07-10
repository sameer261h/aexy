"""Focused tests for the pure CSV import preflight service."""

import socket

import pytest

from aexy.schemas.csv_import import CsvColumnMapping, CsvImportLimits, CsvImportTargetAttribute
from aexy.services.csv_import_preflight_service import CsvImportPreflightService


def _targets(*targets: tuple[str, str, str | None, str, bool | None]) -> list[CsvImportTargetAttribute]:
    return [
        CsvImportTargetAttribute(
            id=attribute_id,
            display_name=display_name,
            slug=slug,
            attribute_type=attribute_type,
            importable=importable,
        )
        for attribute_id, display_name, slug, attribute_type, importable in targets
    ]


def _codes(result) -> list[str]:
    return [issue.code for issue in result.errors]


def _warning_codes(result) -> list[str]:
    return [issue.code for issue in result.warnings]


@pytest.fixture
def service() -> CsvImportPreflightService:
    return CsvImportPreflightService()


def test_valid_utf8_csv_parses_successfully(service):
    result = service.preflight(b"Name,Email\nAda,ada@example.com\n", [])

    assert result.eligible_to_proceed is True
    assert result.encoding == "utf-8"
    assert result.original_headers == ["Name", "Email"]
    assert result.preview_rows[0].values == ["Ada", "ada@example.com"]


def test_utf8_bom_is_handled(service):
    result = service.preflight(b"\xef\xbb\xbfName\nAda\n", [])

    assert result.eligible_to_proceed is True
    assert result.encoding == "utf-8-sig"
    assert result.original_headers == ["Name"]


@pytest.mark.parametrize(
    ("raw_csv", "expected"),
    [
        (b'Name,Company\nAda,"Acme, Inc."\n', ["Ada", "Acme, Inc."]),
        (b'Name,Note\nAda,"She said ""hello"""\n', ["Ada", 'She said "hello"']),
        (b'Name,Note\nAda,"first line\nsecond line"\n', ["Ada", "first line\nsecond line"]),
        (b"Name,Email\r\nAda,ada@example.com\r\n", ["Ada", "ada@example.com"]),
        (b"Name,Email\nAda,\n", ["Ada", ""]),
    ],
)
def test_standards_compliant_csv_variants_parse(service, raw_csv, expected):
    result = service.preflight(raw_csv, [])

    assert result.eligible_to_proceed is True
    assert result.preview_rows[0].values == expected


def test_invalid_utf8_is_rejected(service):
    result = service.preflight(b"Name\n\xff\n", [])

    assert _codes(result) == ["INVALID_ENCODING"]
    assert result.eligible_to_proceed is False


def test_malformed_csv_is_rejected(service):
    result = service.preflight(b'Name,Note\nAda,"unterminated\n', [])

    assert _codes(result) == ["MALFORMED_CSV"]
    assert result.eligible_to_proceed is False


@pytest.mark.parametrize(
    "raw_csv, expected_code",
    [
        (b"", "EMPTY_FILE"),
        (b"\n\n", "MISSING_HEADER"),
        (b"Name, \nAda,1\n", "BLANK_HEADER"),
        (b"First Name,first_name\nAda,Ada\n", "DUPLICATE_NORMALIZED_HEADER"),
        (b"Name,Email\nAda\n", "ROW_WIDTH_MISMATCH"),
    ],
)
def test_header_and_row_structure_errors_are_rejected(service, raw_csv, expected_code):
    result = service.preflight(raw_csv, [])

    assert expected_code in _codes(result)
    assert result.eligible_to_proceed is False


@pytest.mark.parametrize(
    ("raw_csv", "limits", "expected_code"),
    [
        (b"Name\nAda\n", CsvImportLimits(max_file_size_bytes=4), "FILE_SIZE_LIMIT_EXCEEDED"),
        (b"Name\nAda\nGrace\n", CsvImportLimits(max_data_rows=1), "ROW_COUNT_LIMIT_EXCEEDED"),
        (b"A,B\n1,2\n", CsvImportLimits(max_columns=1), "COLUMN_COUNT_LIMIT_EXCEEDED"),
        (b"Name\nTooLong\n", CsvImportLimits(max_cell_length=3), "CELL_LENGTH_LIMIT_EXCEEDED"),
    ],
)
def test_safety_limits_are_enforced(service, raw_csv, limits, expected_code):
    result = service.preflight(raw_csv, [], limits=limits)

    assert expected_code in _codes(result)
    assert result.eligible_to_proceed is False


def test_row_limit_error_retains_accepted_row_count(service):
    result = service.preflight(
        b"Name\nAda\nGrace\n",
        [],
        limits=CsvImportLimits(max_data_rows=1),
    )

    assert _codes(result) == ["ROW_COUNT_LIMIT_EXCEEDED"]
    assert result.original_headers == ["Name"]
    assert result.total_data_row_count == 1


def test_preview_is_bounded_and_total_count_is_complete(service):
    result = service.preflight(
        b"Name\nAda\nGrace\nLin\n",
        [],
        limits=CsvImportLimits(max_preview_rows=2),
    )

    assert result.total_data_row_count == 3
    assert [row.values for row in result.preview_rows] == [["Ada"], ["Grace"]]
    assert result.preview_truncated is True
    assert "PREVIEW_TRUNCATED" in _warning_codes(result)


def test_header_only_csv_is_a_deterministic_warning(service):
    result = service.preflight(b"Name,Email\n", [])

    assert result.eligible_to_proceed is True
    assert result.total_data_row_count == 0
    assert "HEADER_ONLY_CSV" in _warning_codes(result)


def test_blank_physical_rows_are_skipped_with_warning(service):
    result = service.preflight(b"Name\n\nAda\n\n", [])

    assert result.eligible_to_proceed is True
    assert result.total_data_row_count == 1
    assert "BLANK_ROWS_SKIPPED" in _warning_codes(result)


def test_exact_display_name_mapping_suggestion(service):
    result = service.preflight(
        b"First Name\nAda\n",
        _targets(("first", "First Name", "first_name", "text", None)),
    )

    assert result.mapping_suggestions[0].target_attribute_id == "first"
    assert result.mapping_suggestions[0].match_reason == "display_name_exact"


def test_exact_slug_mapping_suggestion(service):
    result = service.preflight(
        b"work_email\nada@example.com\n",
        _targets(("email", "Email address", "work_email", "email", None)),
    )

    assert result.mapping_suggestions[0].target_attribute_id == "email"
    assert result.mapping_suggestions[0].match_reason == "slug_exact"


def test_ambiguous_matches_are_not_guessed(service):
    result = service.preflight(
        b"Name\nAda\n",
        _targets(
            ("one", "Name", "one", "text", None),
            ("two", "Name", "two", "text", None),
        ),
    )

    assert result.mapping_suggestions == []
    assert "AMBIGUOUS_ATTRIBUTE_MATCH" in _warning_codes(result)


def test_valid_mapping_is_accepted_and_unmapped_columns_are_allowed(service):
    targets = _targets(("name", "Name", "name", "text", None))
    mapping = [CsvColumnMapping(source_header="Name", target_attribute_id="name")]

    result = service.preflight(b"Name,Note\nAda,hello\n", targets, mapping)

    assert result.eligible_to_proceed is True
    assert result.validated_mapping == mapping
    assert [issue.source_header for issue in result.warnings if issue.code == "UNMAPPED_SOURCE_COLUMN"] == [
        "Note"
    ]


@pytest.mark.parametrize(
    "mapping, expected_code",
    [
        ([CsvColumnMapping(source_header="Missing", target_attribute_id="name")], "UNKNOWN_SOURCE_COLUMN"),
        ([CsvColumnMapping(source_header="Name", target_attribute_id="missing")], "UNKNOWN_TARGET_ATTRIBUTE"),
        (
            [
                CsvColumnMapping(source_header="Name", target_attribute_id="name"),
                CsvColumnMapping(source_header="Email", target_attribute_id="name"),
            ],
            "DUPLICATE_TARGET_MAPPING",
        ),
        (
            [
                CsvColumnMapping(source_header="Name", target_attribute_id="name"),
                CsvColumnMapping(source_header="Name", target_attribute_id="email"),
            ],
            "DUPLICATE_SOURCE_MAPPING",
        ),
    ],
)
def test_invalid_mapping_references_are_rejected(service, mapping, expected_code):
    targets = _targets(
        ("name", "Name", "name", "text", None),
        ("email", "Email", "email", "email", None),
    )
    result = service.preflight(b"Name,Email\nAda,ada@example.com\n", targets, mapping)

    assert expected_code in _codes(result)
    assert result.eligible_to_proceed is False


def test_explicitly_non_importable_or_computed_targets_are_rejected(service):
    targets = _targets(
        ("blocked", "Blocked", "blocked", "text", False),
        ("computed", "Computed", "computed", "ai_computed", None),
    )

    blocked = service.preflight(
        b"Blocked\nvalue\n",
        targets,
        [CsvColumnMapping(source_header="Blocked", target_attribute_id="blocked")],
    )
    computed = service.preflight(
        b"Computed\nvalue\n",
        targets,
        [CsvColumnMapping(source_header="Computed", target_attribute_id="computed")],
    )

    assert _codes(blocked) == ["TARGET_ATTRIBUTE_NOT_IMPORTABLE"]
    assert _codes(computed) == ["TARGET_ATTRIBUTE_NOT_IMPORTABLE"]


def test_inputs_are_not_mutated_and_no_network_access_occurs(service, monkeypatch):
    raw_csv = b"Name\nAda\n"
    targets = _targets(("name", "Name", "name", "text", None))
    mapping = [CsvColumnMapping(source_header="Name", target_attribute_id="name")]

    def fail_socket(*args, **kwargs):
        raise AssertionError("preflight must not create sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    result = service.preflight(raw_csv, targets, mapping)

    assert raw_csv == b"Name\nAda\n"
    assert targets[0].display_name == "Name"
    assert mapping[0].source_header == "Name"
    assert result.eligible_to_proceed is True
