"""Rejection CSV generation from a stable dry-run result.

Pure and deterministic: the same `CsvImportDryRunPolicyResult` always
produces byte-identical CSV output. Only rows with `status == "invalid"`
are included -- create/update/skipped-duplicate candidates were not
rejected and do not belong in a remediation file. Every exported cell is
neutralized against spreadsheet-formula injection, using the six-prefix
convention (`=`/`+`/`-`/`@`/tab/carriage-return) also used by CRM table
export elsewhere in this repository (that feature lives on a sibling
branch not in this branch's history, so the technique is reimplemented
here rather than imported).
"""

import csv
import io
from typing import Any

from aexy.schemas.csv_import_policy import CsvImportDryRunPolicyResult

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _neutralize(value: str) -> str:
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    return str(value)


def generate_rejection_csv(result: CsvImportDryRunPolicyResult) -> bytes:
    """Build the downloadable rejection CSV. Column layout is stable for a
    given result: row_number, reason_codes, remediation, then every source
    header referenced by a rejected row (first-seen order), then every
    destination attribute key referenced by a rejected row (first-seen
    order)."""
    rejected = [row for row in result.rows if row.status == "invalid"]

    source_headers: list[str] = []
    seen_headers: set[str] = set()
    target_keys: list[str] = []
    seen_targets: set[str] = set()
    for row in rejected:
        for header in row.source_values:
            if header not in seen_headers:
                seen_headers.add(header)
                source_headers.append(header)
        for key in row.proposed_values:
            if key not in seen_targets:
                seen_targets.add(key)
                target_keys.append(key)

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([
        _neutralize(cell)
        for cell in ["row_number", "reason_codes", "remediation", *source_headers, *target_keys]
    ])
    for row in rejected:
        cells = [
            str(row.source_row_number),
            ";".join(row.reason_codes),
            ";".join(row.remediation),
            *(_stringify(row.source_values.get(header, "")) for header in source_headers),
            *(_stringify(row.proposed_values.get(key)) for key in target_keys),
        ]
        writer.writerow([_neutralize(cell) for cell in cells])

    return buffer.getvalue().encode("utf-8-sig")


__all__ = ["generate_rejection_csv"]
