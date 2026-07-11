"""Focused tests for the rejection-CSV serialization boundary: complete
formula-neutralization coverage. Constructs `CsvImportDryRunPolicyResult`
directly rather than going through the API/dry-run pipeline -- these are
properties of the pure serialization function itself."""

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


def test_negative_numeric_value_is_still_neutralized_at_export_boundary():
    # A literal leading "-" is one of the six dangerous prefixes -- this is
    # a deliberate, spec-mandated tradeoff (formula neutralization applies
    # uniformly to every exported cell; it does not special-case "looks
    # like a negative number").
    row = _invalid_row(source_values={"balance": "-42"})
    raw = generate_rejection_csv(_result([row]))
    rows = _rows_from_csv(raw)
    header, data = rows[0], rows[1]
    values_by_header = dict(zip(header, data, strict=True))
    assert values_by_header["balance"] == "'-42"


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
