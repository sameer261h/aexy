"""Focused tests for the rejection-CSV serialization boundary: complete
formula-neutralization coverage, and unambiguous, collision-safe column
naming. Constructs `CsvImportDryRunPolicyResult` directly rather than
going through the API/dry-run pipeline -- these are properties of the
pure serialization function itself."""

import csv
import io

from aexy.schemas.csv_import_policy import (
    CsvImportDryRunPolicyResult,
    CsvImportDryRunSummary,
    CsvRowDryRunOutcome,
)
from aexy.services.csv_import_rejection_csv_service import generate_rejection_csv


def _result(rows: list[CsvRowDryRunOutcome]) -> CsvImportDryRunPolicyResult:
    return CsvImportDryRunPolicyResult(
        filename="test.csv",
        dry_run_completed=True,
        summary=CsvImportDryRunSummary(),
        rows=rows,
    )


def _invalid_row(source_values: dict, proposed_values: dict | None = None, source_row_number: int = 2) -> CsvRowDryRunOutcome:
    return CsvRowDryRunOutcome(
        source_row_number=source_row_number,
        status="invalid",
        reason_codes=["SOME_CODE"],
        remediation=["Fix it."],
        source_values=source_values,
        proposed_values=proposed_values or {},
        matched_existing=False,
    )


def _rows_from_csv(raw: bytes) -> list[list[str]]:
    text = raw.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


# -- Formula neutralization: all six dangerous prefixes -----------------------

def test_neutralizes_all_six_dangerous_prefixes():
    dangerous = {
        "equals": "=SUM(A1:A2)",
        "plus": "+1+1",
        "minus": "-1-1",
        "at": "@SUM(A1)",
        "tab": "\t=SUM(A1:A2)",
        "cr": "\r=SUM(A1:A2)",
    }
    row = _invalid_row(source_values=dangerous)
    raw = generate_rejection_csv(_result([row]))
    rows = _rows_from_csv(raw)
    header, data = rows[0], rows[1]
    values_by_header = dict(zip(header, data, strict=True))
    for key, payload in dangerous.items():
        cell = values_by_header[key]
        assert cell.startswith("'"), f"{key!r} cell {cell!r} was not neutralized"
        assert cell == "'" + payload


def test_safe_ordinary_values_pass_through_unmodified():
    safe = {
        "plain_text": "Ada Lovelace",
        "zero": "0",
        "false_text": "false",
        "empty_string": "",
        "whitespace_text": "  has leading and trailing space around ordinary text  ",
    }
    row = _invalid_row(source_values=safe)
    raw = generate_rejection_csv(_result([row]))
    rows = _rows_from_csv(raw)
    header, data = rows[0], rows[1]
    values_by_header = dict(zip(header, data, strict=True))
    assert values_by_header["plain_text"] == "Ada Lovelace"
    assert values_by_header["zero"] == "0"
    assert values_by_header["false_text"] == "false"
    assert values_by_header["empty_string"] == ""
    # Whitespace-containing ordinary text is preserved verbatim, not trimmed.
    assert values_by_header["whitespace_text"] == "  has leading and trailing space around ordinary text  "


def test_proposed_value_zero_and_false_are_not_treated_as_dangerous():
    row = _invalid_row(
        source_values={"name": "Ada"},
        proposed_values={"count": 0, "active": False},
    )
    raw = generate_rejection_csv(_result([row]))
    rows = _rows_from_csv(raw)
    header, data = rows[0], rows[1]
    values_by_header = dict(zip(header, data, strict=True))
    assert values_by_header[[h for h in header if h.endswith("count")][0]] == "0"
    assert values_by_header[[h for h in header if h.endswith("active")][0]] == "False"


def test_negative_source_string_value_is_still_neutralized_at_export_boundary():
    # A source value is always raw CSV text (a string), even when it looks
    # numeric -- a literal leading "-" is one of the six dangerous
    # prefixes, so it is neutralized like any other string cell. This is
    # distinct from a *typed* proposed numeric value (see
    # test_typed_negative_numeric_proposed_value_is_never_neutralized),
    # which is not text and must never be apostrophe-prefixed.
    row = _invalid_row(source_values={"balance": "-42"})
    raw = generate_rejection_csv(_result([row]))
    rows = _rows_from_csv(raw)
    header, data = rows[0], rows[1]
    values_by_header = dict(zip(header, data, strict=True))
    assert values_by_header["balance"] == "'-42"


def test_typed_negative_numeric_proposed_value_is_never_neutralized():
    # A typed int/float proposed value is not text -- it must be written
    # verbatim. Apostrophe-prefixing -123 would corrupt it into a
    # different string for anyone re-importing this file; the "-" here is
    # the number's sign, not a spreadsheet formula.
    row = _invalid_row(
        source_values={"name": "Ada"},
        proposed_values={"balance": -123, "ratio": -0.5},
    )
    raw = generate_rejection_csv(_result([row]))
    rows = _rows_from_csv(raw)
    header, data = rows[0], rows[1]
    values_by_header = dict(zip(header, data, strict=True))
    assert values_by_header[[h for h in header if h.endswith("balance")][0]] == "-123"
    assert values_by_header[[h for h in header if h.endswith("ratio")][0]] == "-0.5"


def test_typed_negative_numeric_proposed_value_survives_round_trip_reparse():
    row = _invalid_row(source_values={}, proposed_values={"balance": -123})
    raw = generate_rejection_csv(_result([row]))
    header, data = _rows_from_csv(raw)[0], _rows_from_csv(raw)[1]
    values_by_header = dict(zip(header, data, strict=True))
    cell = values_by_header[[h for h in header if h.endswith("balance")][0]]
    assert cell == "-123"
    assert int(cell) == -123


def test_metadata_columns_and_diagnostics_are_neutralized():
    row = CsvRowDryRunOutcome(
        source_row_number=2,
        status="invalid",
        reason_codes=["=EVIL_CODE"],
        remediation=["=EVIL_REMEDIATION"],
        source_values={},
        proposed_values={},
        matched_existing=False,
    )
    raw = generate_rejection_csv(_result([row]))
    text = raw.decode("utf-8-sig")
    assert "'=EVIL_CODE" in text
    assert "'=EVIL_REMEDIATION" in text


def test_source_values_are_never_silently_trimmed():
    row = _invalid_row(source_values={"name": "  Ada Lovelace  "})
    raw = generate_rejection_csv(_result([row]))
    rows = _rows_from_csv(raw)
    header, data = rows[0], rows[1]
    values_by_header = dict(zip(header, data, strict=True))
    assert values_by_header["name"] == "  Ada Lovelace  "


# -- Column naming: source headers preserved, Aexy columns reserved-prefixed --

def test_metadata_columns_use_reserved_aexy_prefix():
    row = _invalid_row(source_values={"Name": "Ada"})
    raw = generate_rejection_csv(_result([row]))
    header = _rows_from_csv(raw)[0]
    assert "__aexy_row_number" in header
    assert "__aexy_reason_codes" in header
    assert "__aexy_remediation" in header


def test_source_header_name_and_destination_slug_name_do_not_collide():
    row = _invalid_row(source_values={"Name": "Ada"}, proposed_values={"name": "Ada"})
    raw = generate_rejection_csv(_result([row]))
    header = _rows_from_csv(raw)[0]
    assert "Name" in header  # original source header, unchanged
    assert "__aexy_proposed_name" in header  # prefixed destination column
    assert header.count("Name") == 1
    assert header.count("__aexy_proposed_name") == 1


def test_source_header_row_number_is_preserved_unchanged():
    row = _invalid_row(source_values={"row_number": "42"})
    raw = generate_rejection_csv(_result([row]))
    header = _rows_from_csv(raw)[0]
    assert "row_number" in header
    assert "__aexy_row_number" in header
    assert header.index("row_number") != header.index("__aexy_row_number")


def test_source_header_colliding_with_reserved_metadata_name_disambiguates_generated_column():
    row = _invalid_row(source_values={"__aexy_row_number": "user-supplied"})
    raw = generate_rejection_csv(_result([row]))
    header = _rows_from_csv(raw)[0]
    # The user's source header is preserved verbatim...
    assert "__aexy_row_number" in header
    # ...and the generated row-number column is deterministically renamed
    # rather than colliding with it.
    assert "__aexy_row_number__2" in header
    data = _rows_from_csv(raw)[1]
    values_by_header = dict(zip(header, data, strict=True))
    assert values_by_header["__aexy_row_number"] == "user-supplied"
    assert values_by_header["__aexy_row_number__2"] == "2"


def test_destination_slugs_differing_only_by_case_are_deterministically_disambiguated():
    # Collision detection is case-insensitive: "Name" and "name" would be
    # the same column under a case-insensitive spreadsheet re-import, so
    # the second one seen is deterministically suffixed rather than
    # colliding. The first-seen header keeps its natural, unsuffixed
    # casing.
    row = _invalid_row(source_values={}, proposed_values={"Name": "Ada", "name": "ada"})
    raw = generate_rejection_csv(_result([row]))
    header = _rows_from_csv(raw)[0]
    assert "__aexy_proposed_Name" in header
    assert "__aexy_proposed_name__2" in header
    assert "__aexy_proposed_name" not in header
    assert header.count("__aexy_proposed_Name") == 1
    assert header.count("__aexy_proposed_name__2") == 1
    data = _rows_from_csv(raw)[1]
    values_by_header = dict(zip(header, data, strict=True))
    assert values_by_header["__aexy_proposed_Name"] == "Ada"
    assert values_by_header["__aexy_proposed_name__2"] == "ada"


def test_source_header_colliding_only_by_case_with_reserved_metadata_name_disambiguates():
    row = _invalid_row(source_values={"__AEXY_ROW_NUMBER": "user-supplied"})
    raw = generate_rejection_csv(_result([row]))
    header = _rows_from_csv(raw)[0]
    # The user's source header is preserved verbatim, including its casing...
    assert "__AEXY_ROW_NUMBER" in header
    # ...and the generated row-number column is deterministically renamed
    # rather than colliding case-insensitively with it.
    assert "__aexy_row_number__2" in header
    assert "__aexy_row_number" not in header


def test_column_generation_is_deterministic_across_repeated_calls():
    row = _invalid_row(
        source_values={"Name": "Ada", "__aexy_row_number": "collide"},
        proposed_values={"name": "ada", "Name": "Ada"},
    )
    raw1 = generate_rejection_csv(_result([row]))
    raw2 = generate_rejection_csv(_result([row]))
    assert raw1 == raw2


def test_formula_neutralization_applies_to_generated_and_original_headers():
    row = _invalid_row(source_values={"=Name": "Ada"})
    raw = generate_rejection_csv(_result([row]))
    header = _rows_from_csv(raw)[0]
    assert "'=Name" in header
