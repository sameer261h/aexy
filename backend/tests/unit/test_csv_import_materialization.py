"""Focused tests for pure CSV row materialization."""

import socket

import pytest

from aexy.schemas.csv_import import CsvColumnMapping
from aexy.schemas.csv_import_materialization import (
    CsvMaterializationOptions,
    CsvMaterializationTargetAttribute,
)
from aexy.services.csv_import_materialization_service import (
    CsvImportMaterializationService,
)


def _target(
    attribute_id: str,
    display_name: str,
    attribute_type: str,
    *,
    slug: str | None = None,
    config: dict | None = None,
    importable: bool | None = None,
) -> CsvMaterializationTargetAttribute:
    return CsvMaterializationTargetAttribute(
        id=attribute_id,
        display_name=display_name,
        slug=slug or attribute_id,
        attribute_type=attribute_type,
        config=config or {},
        importable=importable,
    )


def _mapping(*pairs: tuple[str, str]) -> list[CsvColumnMapping]:
    return [CsvColumnMapping(source_header=source, target_attribute_id=target) for source, target in pairs]


def _codes(result) -> list[str]:
    return [issue.code for issue in result.errors]


@pytest.fixture
def service() -> CsvImportMaterializationService:
    return CsvImportMaterializationService()


def test_valid_text_field_uses_target_slug_and_row_number(service):
    result = service.materialize(
        12,
        {"Name": "Ada"},
        _mapping(("Name", "name")),
        [_target("name", "Name", "text")],
    )

    assert result.source_row_number == 12
    assert result.record_values == {"name": "Ada"}
    assert result.fields[0].conversion_succeeded is True
    assert result.eligible_to_proceed is True


def test_multiple_fields_keep_mapping_order_and_unmapped_columns_are_ignored(service):
    result = service.materialize(
        1,
        {"First Name": "Ada", "Age": "37", "Ignored": "x"},
        _mapping(("First Name", "name"), ("Age", "age")),
        [_target("name", "Name", "text"), _target("age", "Age", "number")],
    )

    assert list(result.record_values) == ["name", "age"]
    assert [field.target_key for field in result.fields] == ["name", "age"]
    assert result.record_values == {"name": "Ada", "age": 37}


def test_normalized_source_header_is_accepted_without_mutating_inputs(service):
    source_cells = {"first_name": "Ada"}
    mapping = _mapping(("First Name", "name"))
    targets = [_target("name", "Name", "text")]

    result = service.materialize(4, source_cells, mapping, targets)

    assert result.record_values == {"name": "Ada"}
    assert source_cells == {"first_name": "Ada"}
    assert mapping == _mapping(("First Name", "name"))
    assert targets[0].config == {}


def test_blank_values_follow_type_contract(service):
    targets = [
        _target("text", "Text", "text"),
        _target("number", "Number", "number"),
        _target("flag", "Flag", "checkbox"),
        _target("tags", "Tags", "multi_select", config={"options": ["A"]}),
    ]
    result = service.materialize(
        1,
        {"Text": "", "Number": "", "Flag": "", "Tags": ""},
        _mapping(("Text", "text"), ("Number", "number"), ("Flag", "flag"), ("Tags", "tags")),
        targets,
        options=CsvMaterializationOptions(multi_select_delimiter=","),
    )

    assert result.record_values == {"text": "", "number": None, "flag": None, "tags": []}
    assert result.eligible_to_proceed is True


def test_valid_decimal_safe_number_conversion(service):
    result = service.materialize(
        1,
        {"Amount": "12.50"},
        _mapping(("Amount", "amount")),
        [_target("amount", "Amount", "currency")],
    )

    assert result.record_values == {"amount": 12.5}


@pytest.mark.parametrize("raw_value", ["12x", "1,234", " 12"])
def test_invalid_number_is_rejected(service, raw_value):
    result = service.materialize(
        2,
        {"Amount": raw_value},
        _mapping(("Amount", "amount")),
        [_target("amount", "Amount", "number")],
    )

    assert _codes(result) == ["INVALID_NUMBER"]
    assert result.eligible_to_proceed is False


@pytest.mark.parametrize("raw_value", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_number_is_rejected(service, raw_value):
    result = service.materialize(
        2,
        {"Amount": raw_value},
        _mapping(("Amount", "amount")),
        [_target("amount", "Amount", "number")],
    )

    assert _codes(result) == ["NON_FINITE_NUMBER"]
    assert result.eligible_to_proceed is False


@pytest.mark.parametrize(("raw_value", "expected"), [("true", True), ("false", False)])
def test_valid_boolean_tokens(service, raw_value, expected):
    result = service.materialize(
        3,
        {"Enabled": raw_value},
        _mapping(("Enabled", "enabled")),
        [_target("enabled", "Enabled", "checkbox")],
    )

    assert result.record_values == {"enabled": expected}


def test_invalid_boolean_token_is_rejected(service):
    result = service.materialize(
        3,
        {"Enabled": "yes"},
        _mapping(("Enabled", "enabled")),
        [_target("enabled", "Enabled", "checkbox")],
    )

    assert _codes(result) == ["INVALID_BOOLEAN"]


def test_valid_date_and_datetime_conversion(service):
    targets = [_target("date", "Date", "date"), _target("when", "When", "timestamp")]
    result = service.materialize(
        5,
        {"Date": "2026-07-11", "When": "2026-07-11T14:30"},
        _mapping(("Date", "date"), ("When", "when")),
        targets,
    )

    assert result.record_values == {"date": "2026-07-11", "when": "2026-07-11T14:30"}


@pytest.mark.parametrize(
    ("attribute_type", "raw_value", "expected_code"),
    [("date", "07/11/2026", "INVALID_DATE"), ("date", "2026-02-30", "INVALID_DATE"), ("timestamp", "2026-07-11", "INVALID_DATETIME"), ("timestamp", "not-a-date", "INVALID_DATETIME")],
)
def test_invalid_or_ambiguous_dates_are_rejected(service, attribute_type, raw_value, expected_code):
    result = service.materialize(
        5,
        {"When": raw_value},
        _mapping(("When", "when")),
        [_target("when", "When", attribute_type)],
    )

    assert _codes(result) == [expected_code]


def test_exact_select_option_match_returns_canonical_value(service):
    result = service.materialize(
        6,
        {"Stage": "Won"},
        _mapping(("Stage", "stage")),
        [_target("stage", "Stage", "status", config={"options": [{"value": "won", "label": "Won"}]})],
    )

    assert result.record_values == {"stage": "won"}


def test_unknown_and_ambiguous_select_options_are_rejected(service):
    unknown = service.materialize(
        6,
        {"Stage": "Maybe"},
        _mapping(("Stage", "stage")),
        [_target("stage", "Stage", "select", config={"options": ["Won", "Lost"]})],
    )
    ambiguous = service.materialize(
        6,
        {"Stage": "new"},
        _mapping(("Stage", "stage")),
        [_target("stage", "Stage", "select", config={"options": ["new", "NEW"]})],
    )

    assert _codes(unknown) == ["UNKNOWN_SELECT_OPTION"]
    assert _codes(ambiguous) == ["AMBIGUOUS_SELECT_OPTION"]


def test_multi_select_conversion_and_unknown_entry(service):
    target = _target("tags", "Tags", "multi_select", config={"options": ["A", "B"]})
    valid = service.materialize(
        7,
        {"Tags": "A, B"},
        _mapping(("Tags", "tags")),
        [target],
        options=CsvMaterializationOptions(multi_select_delimiter=","),
    )
    invalid = service.materialize(
        7,
        {"Tags": "A, C"},
        _mapping(("Tags", "tags")),
        [target],
        options=CsvMaterializationOptions(multi_select_delimiter=","),
    )

    assert valid.record_values == {"tags": ["A", "B"]}
    assert _codes(invalid) == ["INVALID_MULTI_SELECT"]


def test_unsupported_reference_and_non_importable_target_are_rejected(service):
    reference = service.materialize(
        8,
        {"Company": "company-id"},
        _mapping(("Company", "company")),
        [_target("company", "Company", "record_reference")],
    )
    blocked = service.materialize(
        8,
        {"Computed": "value"},
        _mapping(("Computed", "computed")),
        [_target("computed", "Computed", "text", importable=False)],
    )

    assert _codes(reference) == ["UNSUPPORTED_ATTRIBUTE_TYPE"]
    assert _codes(blocked) == ["TARGET_ATTRIBUTE_NOT_IMPORTABLE"]


def test_missing_source_and_cell_length_errors_are_structured(service):
    missing = service.materialize(
        9,
        {},
        _mapping(("Missing", "name")),
        [_target("name", "Name", "text")],
    )
    too_long = service.materialize(
        9,
        {"Name": "abcdef"},
        _mapping(("Name", "name")),
        [_target("name", "Name", "text")],
        options=CsvMaterializationOptions(max_cell_length=3),
    )

    assert _codes(missing) == ["MISSING_MAPPED_SOURCE_COLUMN"]
    assert _codes(too_long) == ["CELL_VALUE_TOO_LONG"]
    assert missing.errors[0].row_number == 9
    assert too_long.errors[0].source_header == "Name"


def test_multiple_errors_keep_deterministic_order_and_valid_fields_visible(service):
    result = service.materialize(
        10,
        {"Name": "Ada", "Age": "bad", "Enabled": "maybe"},
        _mapping(("Name", "name"), ("Age", "age"), ("Enabled", "enabled")),
        [
            _target("name", "Name", "text"),
            _target("age", "Age", "number"),
            _target("enabled", "Enabled", "checkbox"),
        ],
    )

    assert _codes(result) == ["INVALID_NUMBER", "INVALID_BOOLEAN"]
    assert result.record_values == {"name": "Ada"}
    assert [field.conversion_succeeded for field in result.fields] == [True, False, False]
    assert result.eligible_to_proceed is False


def test_no_database_or_network_access_and_no_input_mutation(service, monkeypatch):
    source_cells = {"Name": "Ada"}
    mapping = _mapping(("Name", "name"))
    targets = [_target("name", "Name", "text")]

    def fail_socket(*args, **kwargs):
        raise AssertionError("materialization must not create sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    result = service.materialize(11, source_cells, mapping, targets)

    assert result.eligible_to_proceed is True
    assert source_cells == {"Name": "Ada"}
    assert mapping == _mapping(("Name", "name"))
    assert targets[0].display_name == "Name"
