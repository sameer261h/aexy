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

Column naming: original source headers are preserved byte-for-byte --
users correct and re-upload those columns, so renaming them would break
that workflow. Every Aexy-generated column (row number, reason codes,
remediation, proposed destination values) is prefixed with the reserved
`__aexy_` namespace instead, so a source header that happens to collide
with a destination slug (e.g. a CSV column literally named `name`) can
never become ambiguous with a generated column. If a source header
happens to already use the reserved `__aexy_` namespace, the *generated*
header is deterministically disambiguated -- the user's source header is
never altered. Collision detection is case-insensitive (casefolded), so
two destination slugs differing only by case still both get distinct,
deterministic columns without silently colliding under a
case-insensitive spreadsheet import elsewhere -- but the header text
itself keeps its original, human-chosen casing.

Formula neutralization applies only to string-shaped cells (original CSV
source strings, joined reason-code/remediation text, and string/list-
typed proposed values). A typed numeric or boolean proposed value (e.g.
`-123`, `False`) is written as-is: apostrophe-prefixing `-123` would
silently turn a valid negative number into a different, corrupted string
for anyone re-importing this file, and the "-" there is not a formula,
it's the number's sign.
"""

import csv
import io
from typing import Any

from aexy.schemas.csv_import_policy import CsvImportDryRunPolicyResult

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_ROW_NUMBER_HEADER = "__aexy_row_number"
_REASON_CODES_HEADER = "__aexy_reason_codes"
_REMEDIATION_HEADER = "__aexy_remediation"
_PROPOSED_VALUE_PREFIX = "__aexy_proposed_"


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


def _neutralize_proposed_value(value: Any) -> str:
    """Stringify a proposed destination value, neutralizing it only if it
    is string-shaped. `int`/`float` (which also covers `bool`, a `int`
    subclass in Python) are typed scalars, not text -- they are written
    verbatim, preserving e.g. a negative number's sign."""
    stringified = _stringify(value)
    if isinstance(value, (int, float)):
        return stringified
    return _neutralize(stringified)


def _proposed_value_header(target_key: str) -> str:
    return f"{_PROPOSED_VALUE_PREFIX}{target_key}"


def _disambiguate(preferred: str, taken: dict[str, str]) -> str:
    """Deterministically rename an Aexy-generated header if it collides
    (case-insensitively) with a header already claimed by a source column
    or an earlier Aexy-generated column. Only ever called for generated
    names -- source headers are never passed through this function and
    are never renamed. `taken` maps casefolded keys to the exact string
    already claiming that key, purely so collisions are detected without
    regard to case while every returned header keeps its original,
    human-chosen casing."""
    key = preferred.casefold()
    if key not in taken:
        taken[key] = preferred
        return preferred
    suffix = 2
    candidate = f"{preferred}__{suffix}"
    candidate_key = candidate.casefold()
    while candidate_key in taken:
        suffix += 1
        candidate = f"{preferred}__{suffix}"
        candidate_key = candidate.casefold()
    taken[candidate_key] = candidate
    return candidate


def generate_rejection_csv(result: CsvImportDryRunPolicyResult) -> bytes:
    """Build the downloadable rejection CSV. Column layout is stable for a
    given result: row-number/reason-codes/remediation metadata columns,
    then every source header referenced by a rejected row (first-seen
    order, unchanged), then every proposed-value column referenced by a
    rejected row (first-seen order, `__aexy_proposed_`-prefixed)."""
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

    taken: dict[str, str] = {header.casefold(): header for header in source_headers}
    row_number_header = _disambiguate(_ROW_NUMBER_HEADER, taken)
    reason_codes_header = _disambiguate(_REASON_CODES_HEADER, taken)
    remediation_header = _disambiguate(_REMEDIATION_HEADER, taken)

    proposed_headers: dict[str, str] = {
        key: _disambiguate(_proposed_value_header(key), taken) for key in target_keys
    }

    header_row = [
        row_number_header, reason_codes_header, remediation_header,
        *source_headers,
        *(proposed_headers[key] for key in target_keys),
    ]

    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([_neutralize(cell) for cell in header_row])
    for row in rejected:
        cells = [
            _neutralize(str(row.source_row_number)),
            _neutralize(";".join(row.reason_codes)),
            _neutralize(";".join(row.remediation)),
            *(_neutralize(_stringify(row.source_values.get(header, ""))) for header in source_headers),
            *(_neutralize_proposed_value(row.proposed_values.get(key)) for key in target_keys),
        ]
        writer.writerow(cells)

    return buffer.getvalue().encode("utf-8-sig")


__all__ = ["generate_rejection_csv"]
