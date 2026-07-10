"""Pure parsing, validation, mapping, and preview support for future CSV imports."""

import csv
import io
import re
from collections.abc import Sequence
from typing import Literal

from aexy.schemas.csv_import import (
    DEFAULT_CSV_IMPORT_LIMITS,
    CsvColumnMapping,
    CsvImportLimits,
    CsvImportPreflightResult,
    CsvImportTargetAttribute,
    CsvMappingSuggestion,
    CsvPreflightIssue,
    CsvPreviewRow,
)


NON_IMPORTABLE_ATTRIBUTE_TYPES = frozenset({"ai_computed"})


def normalize_csv_header(value: str) -> str:
    """Normalize headers for exact, deterministic matching without fuzzy inference."""
    trimmed = value.strip().casefold()
    return re.sub(r"[\s_-]+", " ", trimmed).strip()


def _issue_sort_key(issue: CsvPreflightIssue) -> tuple[int, int, str, str, str]:
    return (
        issue.row_number if issue.row_number is not None else -1,
        issue.column_number if issue.column_number is not None else -1,
        issue.code,
        issue.source_header or "",
        issue.target_attribute_id or "",
    )


class CsvImportPreflightService:
    """Perform deterministic CSV preflight without database or network access."""

    def preflight(
        self,
        raw_csv: bytes,
        target_attributes: Sequence[CsvImportTargetAttribute],
        proposed_mapping: Sequence[CsvColumnMapping] | None = None,
        *,
        filename: str | None = None,
        limits: CsvImportLimits = DEFAULT_CSV_IMPORT_LIMITS,
    ) -> CsvImportPreflightResult:
        """Parse and validate CSV input for a later, separate import-execution phase."""
        result = CsvImportPreflightResult(filename=filename)

        if len(raw_csv) > limits.max_file_size_bytes:
            result.errors.append(
                CsvPreflightIssue(
                    code="FILE_SIZE_LIMIT_EXCEEDED",
                    message="CSV file exceeds the configured raw file size limit.",
                    context={"limit_bytes": limits.max_file_size_bytes, "received_bytes": len(raw_csv)},
                )
            )
            return self._finalize(result)

        if not raw_csv:
            result.errors.append(CsvPreflightIssue(code="EMPTY_FILE", message="CSV file is empty."))
            return self._finalize(result)

        try:
            text = raw_csv.decode("utf-8-sig")
        except UnicodeDecodeError:
            result.errors.append(
                CsvPreflightIssue(
                    code="INVALID_ENCODING",
                    message="CSV must be encoded as UTF-8 or UTF-8 with a BOM.",
                )
            )
            return self._finalize(result)

        result.encoding = "utf-8-sig" if raw_csv.startswith(b"\xef\xbb\xbf") else "utf-8"
        if not text:
            result.errors.append(CsvPreflightIssue(code="EMPTY_FILE", message="CSV file is empty."))
            return self._finalize(result)

        parsed_rows = self._parse_rows(text, limits, result)
        if parsed_rows is None:
            return self._finalize(result)

        header, header_line, data_rows, blank_lines = parsed_rows
        self._validate_header(header, header_line, limits, result)
        if result.errors:
            return self._finalize(result)

        result.original_headers = list(header)
        result.normalized_headers = [normalize_csv_header(item) for item in header]
        self._validate_normalized_headers(result)
        if result.errors:
            return self._finalize(result)

        if blank_lines:
            result.warnings.append(
                CsvPreflightIssue(
                    code="BLANK_ROWS_SKIPPED",
                    message="Blank physical CSV rows were skipped.",
                    context={"count": blank_lines},
                )
            )

        self._validate_rows(data_rows, len(header), limits, result)
        if result.errors:
            return self._finalize(result)

        result.total_data_row_count = len(data_rows)
        result.preview_rows = [
            CsvPreviewRow(source_row_number=row_number, values=list(values))
            for row_number, values in data_rows[: limits.max_preview_rows]
        ]
        result.preview_truncated = result.total_data_row_count > len(result.preview_rows)
        if result.preview_truncated:
            result.warnings.append(
                CsvPreflightIssue(
                    code="PREVIEW_TRUNCATED",
                    message="Preview is limited; all accepted rows were still counted.",
                    context={"preview_limit": limits.max_preview_rows},
                )
            )
        if not data_rows:
            result.warnings.append(
                CsvPreflightIssue(
                    code="HEADER_ONLY_CSV",
                    message="CSV contains headers but no data rows.",
                )
            )

        suggestions, suggestion_warnings = self._suggest_mappings(
            header, target_attributes
        )
        result.mapping_suggestions = suggestions
        result.warnings.extend(suggestion_warnings)
        self._validate_mapping(header, target_attributes, proposed_mapping, result)
        self._add_unmapped_column_warnings(header, proposed_mapping, suggestions, result)
        return self._finalize(result)

    def _parse_rows(
        self,
        text: str,
        limits: CsvImportLimits,
        result: CsvImportPreflightResult,
    ) -> tuple[list[str], int, list[tuple[int, list[str]]], int] | None:
        previous_field_limit = csv.field_size_limit()
        try:
            csv.field_size_limit(limits.max_cell_length)
            reader = csv.reader(io.StringIO(text, newline=""), strict=True)
            header: list[str] | None = None
            header_line = 0
            data_rows: list[tuple[int, list[str]]] = []
            blank_lines = 0
            next_source_line = 1
            for row in reader:
                source_line = next_source_line
                next_source_line = reader.line_num + 1
                if not row:
                    blank_lines += 1
                    continue
                if header is None:
                    header = row
                    header_line = source_line
                    continue
                if len(data_rows) >= limits.max_data_rows:
                    result.errors.append(
                        CsvPreflightIssue(
                            code="ROW_COUNT_LIMIT_EXCEEDED",
                            message="CSV exceeds the configured data-row limit.",
                            row_number=source_line,
                            context={"limit_rows": limits.max_data_rows},
                        )
                    )
                    self._retain_partial_parse_metadata(result, header, data_rows)
                    return None
                data_rows.append((source_line, row))
        except csv.Error as error:
            self._retain_partial_parse_metadata(result, header, data_rows)
            if "field larger than field limit" in str(error):
                result.errors.append(
                    CsvPreflightIssue(
                        code="CELL_LENGTH_LIMIT_EXCEEDED",
                        message="A CSV cell exceeds the configured cell-length limit.",
                        context={"limit_characters": limits.max_cell_length},
                    )
                )
            else:
                result.errors.append(
                    CsvPreflightIssue(
                        code="MALFORMED_CSV",
                        message="CSV could not be parsed according to RFC-style CSV rules.",
                    )
                )
            return None
        finally:
            csv.field_size_limit(previous_field_limit)

        if header is None:
            result.errors.append(CsvPreflightIssue(code="MISSING_HEADER", message="CSV has no header row."))
            return None
        return header, header_line, data_rows, blank_lines

    def _retain_partial_parse_metadata(
        self,
        result: CsvImportPreflightResult,
        header: list[str] | None,
        data_rows: list[tuple[int, list[str]]],
    ) -> None:
        """Keep safe, bounded progress information when parsing stops on an error."""
        if header is not None:
            result.original_headers = list(header)
            result.normalized_headers = [normalize_csv_header(item) for item in header]
        result.total_data_row_count = len(data_rows)

    def _validate_header(
        self,
        header: list[str],
        header_line: int,
        limits: CsvImportLimits,
        result: CsvImportPreflightResult,
    ) -> None:
        if not header:
            result.errors.append(CsvPreflightIssue(code="MISSING_HEADER", message="CSV has no header row."))
            return
        if len(header) > limits.max_columns:
            result.errors.append(
                CsvPreflightIssue(
                    code="COLUMN_COUNT_LIMIT_EXCEEDED",
                    message="CSV exceeds the configured column limit.",
                    row_number=header_line,
                    context={"limit_columns": limits.max_columns, "received_columns": len(header)},
                )
            )
        for column_number, value in enumerate(header, start=1):
            if not value.strip():
                result.errors.append(
                    CsvPreflightIssue(
                        code="BLANK_HEADER",
                        message="CSV headers must not be blank.",
                        row_number=header_line,
                        column_number=column_number,
                    )
                )
            if len(value) > limits.max_cell_length:
                result.errors.append(
                    CsvPreflightIssue(
                        code="CELL_LENGTH_LIMIT_EXCEEDED",
                        message="A CSV cell exceeds the configured cell-length limit.",
                        row_number=header_line,
                        column_number=column_number,
                        context={"limit_characters": limits.max_cell_length},
                    )
                )

    def _validate_normalized_headers(self, result: CsvImportPreflightResult) -> None:
        seen: dict[str, int] = {}
        for column_number, normalized in enumerate(result.normalized_headers, start=1):
            if normalized in seen:
                result.errors.append(
                    CsvPreflightIssue(
                        code="DUPLICATE_NORMALIZED_HEADER",
                        message="Two CSV headers normalize to the same deterministic key.",
                        row_number=1,
                        column_number=column_number,
                        source_header=result.original_headers[column_number - 1],
                        context={"first_column_number": seen[normalized]},
                    )
                )
            else:
                seen[normalized] = column_number

    def _validate_rows(
        self,
        data_rows: list[tuple[int, list[str]]],
        expected_width: int,
        limits: CsvImportLimits,
        result: CsvImportPreflightResult,
    ) -> None:
        for row_number, values in data_rows:
            if len(values) != expected_width:
                result.errors.append(
                    CsvPreflightIssue(
                        code="ROW_WIDTH_MISMATCH",
                        message="A CSV data row has a different number of columns than the header.",
                        row_number=row_number,
                        context={"expected_columns": expected_width, "received_columns": len(values)},
                    )
                )
                return
            for column_number, value in enumerate(values, start=1):
                if len(value) > limits.max_cell_length:
                    result.errors.append(
                        CsvPreflightIssue(
                            code="CELL_LENGTH_LIMIT_EXCEEDED",
                            message="A CSV cell exceeds the configured cell-length limit.",
                            row_number=row_number,
                            column_number=column_number,
                            context={"limit_characters": limits.max_cell_length},
                        )
                    )
                    return

    def _suggest_mappings(
        self,
        headers: Sequence[str],
        targets: Sequence[CsvImportTargetAttribute],
    ) -> tuple[list[CsvMappingSuggestion], list[CsvPreflightIssue]]:
        suggestions: list[CsvMappingSuggestion] = []
        warnings: list[CsvPreflightIssue] = []
        for column_number, header in enumerate(headers, start=1):
            normalized = normalize_csv_header(header)
            display_matches = [
                target for target in targets if normalize_csv_header(target.display_name) == normalized
            ]
            if len(display_matches) == 1:
                target = display_matches[0]
                suggestions.append(
                    CsvMappingSuggestion(
                        source_header=header,
                        source_column_number=column_number,
                        target_attribute_id=target.id,
                        target_display_name=target.display_name,
                        match_reason="display_name_exact",
                    )
                )
                continue
            if len(display_matches) > 1:
                warnings.append(self._ambiguous_warning(header, column_number, "display_name"))
                continue

            slug_matches = [
                target
                for target in targets
                if target.slug is not None and normalize_csv_header(target.slug) == normalized
            ]
            if len(slug_matches) == 1:
                target = slug_matches[0]
                suggestions.append(
                    CsvMappingSuggestion(
                        source_header=header,
                        source_column_number=column_number,
                        target_attribute_id=target.id,
                        target_display_name=target.display_name,
                        match_reason="slug_exact",
                    )
                )
            elif len(slug_matches) > 1:
                warnings.append(self._ambiguous_warning(header, column_number, "slug"))
        return suggestions, warnings

    def _ambiguous_warning(
        self, header: str, column_number: int, matching_field: Literal["display_name", "slug"]
    ) -> CsvPreflightIssue:
        return CsvPreflightIssue(
            code="AMBIGUOUS_ATTRIBUTE_MATCH",
            message="A source header exactly matches multiple target attributes; no suggestion was chosen.",
            column_number=column_number,
            source_header=header,
            context={"matching_field": matching_field},
        )

    def _validate_mapping(
        self,
        headers: Sequence[str],
        targets: Sequence[CsvImportTargetAttribute],
        proposed_mapping: Sequence[CsvColumnMapping] | None,
        result: CsvImportPreflightResult,
    ) -> None:
        if proposed_mapping is None:
            return
        target_by_id = {target.id: target for target in targets}
        source_headers = set(headers)
        seen_sources: set[str] = set()
        seen_targets: set[str] = set()
        valid_mapping: list[CsvColumnMapping] = []
        for mapping in proposed_mapping:
            mapping_is_valid = True
            if mapping.source_header not in source_headers:
                result.errors.append(
                    CsvPreflightIssue(
                        code="UNKNOWN_SOURCE_COLUMN",
                        message="Proposed mapping references a CSV source column that does not exist.",
                        source_header=mapping.source_header,
                    )
                )
                mapping_is_valid = False
            elif mapping.source_header in seen_sources:
                result.errors.append(
                    CsvPreflightIssue(
                        code="DUPLICATE_SOURCE_MAPPING",
                        message="A CSV source column may only be mapped once.",
                        source_header=mapping.source_header,
                    )
                )
                mapping_is_valid = False
            else:
                seen_sources.add(mapping.source_header)

            target = target_by_id.get(mapping.target_attribute_id)
            if target is None:
                result.errors.append(
                    CsvPreflightIssue(
                        code="UNKNOWN_TARGET_ATTRIBUTE",
                        message="Proposed mapping references a target attribute that does not exist.",
                        target_attribute_id=mapping.target_attribute_id,
                    )
                )
                mapping_is_valid = False
            elif mapping.target_attribute_id in seen_targets:
                result.errors.append(
                    CsvPreflightIssue(
                        code="DUPLICATE_TARGET_MAPPING",
                        message="A target attribute may only receive one CSV source column.",
                        target_attribute_id=mapping.target_attribute_id,
                    )
                )
                mapping_is_valid = False
            else:
                seen_targets.add(mapping.target_attribute_id)
                if target.importable is False or target.attribute_type in NON_IMPORTABLE_ATTRIBUTE_TYPES:
                    result.errors.append(
                        CsvPreflightIssue(
                            code="TARGET_ATTRIBUTE_NOT_IMPORTABLE",
                            message="Proposed mapping targets an attribute marked as non-importable.",
                            target_attribute_id=target.id,
                        )
                    )
                    mapping_is_valid = False
            if mapping_is_valid:
                valid_mapping.append(mapping.model_copy(deep=True))
        if not result.errors:
            result.validated_mapping = valid_mapping

    def _add_unmapped_column_warnings(
        self,
        headers: Sequence[str],
        proposed_mapping: Sequence[CsvColumnMapping] | None,
        suggestions: Sequence[CsvMappingSuggestion],
        result: CsvImportPreflightResult,
    ) -> None:
        mapped_headers = (
            {mapping.source_header for mapping in proposed_mapping}
            if proposed_mapping is not None
            else {suggestion.source_header for suggestion in suggestions}
        )
        for column_number, header in enumerate(headers, start=1):
            if header not in mapped_headers:
                result.warnings.append(
                    CsvPreflightIssue(
                        code="UNMAPPED_SOURCE_COLUMN",
                        message="CSV source column is not mapped to a target attribute.",
                        column_number=column_number,
                        source_header=header,
                    )
                )

    def _finalize(self, result: CsvImportPreflightResult) -> CsvImportPreflightResult:
        result.errors.sort(key=_issue_sort_key)
        result.warnings.sort(key=_issue_sort_key)
        result.eligible_to_proceed = not result.errors
        return result
