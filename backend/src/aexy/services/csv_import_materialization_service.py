"""Pure conversion of one validated CSV row into candidate CRM values."""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from aexy.schemas.csv_import import (
    CsvColumnMapping,
    CsvImportTargetAttribute,
    CsvPreflightIssue,
)
from aexy.schemas.csv_import_materialization import (
    CsvMaterializationOptions,
    CsvMaterializationTargetAttribute,
    CsvMaterializedField,
    CsvRowMaterializationResult,
)
from aexy.services.csv_import_preflight_service import normalize_csv_header


TEXT_LIKE_TYPES = frozenset(
    {"text", "textarea", "email", "phone", "url", "location", "person_name"}
)
NUMERIC_TYPES = frozenset({"number", "currency", "rating"})
SELECT_TYPES = frozenset({"select", "status"})
UNSUPPORTED_TYPES = frozenset(
    {"record_reference", "user_reference", "file", "ai_computed"}
)
NUMERIC_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class _MaterializationError(Exception):
    def __init__(self, code: str, message: str, context: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = context or {}


class CsvImportMaterializationService:
    """Materialize one CSV row without persistence, I/O, or business policies."""

    def materialize(
        self,
        source_row_number: int,
        source_cells: Mapping[str, str],
        mapping: Sequence[CsvColumnMapping],
        target_attributes: Sequence[
            CsvMaterializationTargetAttribute | CsvImportTargetAttribute
        ],
        *,
        options: CsvMaterializationOptions | None = None,
    ) -> CsvRowMaterializationResult:
        """Convert mapped cells into candidate record values in mapping order."""
        if source_row_number < 1:
            raise ValueError("source_row_number must be at least 1")

        conversion_options = options or CsvMaterializationOptions()
        result = CsvRowMaterializationResult(source_row_number=source_row_number)
        targets = self._copy_targets(target_attributes)
        target_by_id = {target.id: target for target in targets}

        for column_mapping in mapping:
            target = target_by_id.get(column_mapping.target_attribute_id)
            target_key = target.slug or target.id if target else column_mapping.target_attribute_id
            if target is None:
                self._add_error(
                    result,
                    code="UNKNOWN_TARGET_ATTRIBUTE",
                    message="Mapping references target metadata that was not supplied.",
                    source_header=column_mapping.source_header,
                    target_attribute_id=column_mapping.target_attribute_id,
                )
                result.fields.append(
                    CsvMaterializedField(
                        source_header=column_mapping.source_header,
                        target_attribute_id=column_mapping.target_attribute_id,
                        target_key=target_key,
                        conversion_succeeded=False,
                    )
                )
                continue

            source_key, raw_value, source_error = self._resolve_source_cell(
                source_cells, column_mapping.source_header
            )
            if source_error is not None:
                self._add_error(
                    result,
                    code=source_error,
                    message="Mapping references a source column that is missing or ambiguous.",
                    source_header=column_mapping.source_header,
                    target_attribute_id=target.id,
                )
                result.fields.append(
                    CsvMaterializedField(
                        source_header=source_key or column_mapping.source_header,
                        target_attribute_id=target.id,
                        target_key=target_key,
                        conversion_succeeded=False,
                    )
                )
                continue

            if target.importable is False or target.attribute_type == "ai_computed":
                self._add_error(
                    result,
                    code="TARGET_ATTRIBUTE_NOT_IMPORTABLE",
                    message="Target attribute is explicitly marked as non-importable.",
                    source_header=column_mapping.source_header,
                    target_attribute_id=target.id,
                )
                result.fields.append(
                    CsvMaterializedField(
                        source_header=source_key,
                        target_attribute_id=target.id,
                        target_key=target_key,
                        conversion_succeeded=False,
                    )
                )
                continue

            if len(raw_value) > conversion_options.max_cell_length:
                self._add_error(
                    result,
                    code="CELL_VALUE_TOO_LONG",
                    message="Mapped cell exceeds the configured materialization limit.",
                    source_header=source_key,
                    target_attribute_id=target.id,
                    context={"limit_characters": conversion_options.max_cell_length},
                )
                result.fields.append(
                    CsvMaterializedField(
                        source_header=source_key,
                        target_attribute_id=target.id,
                        target_key=target_key,
                        conversion_succeeded=False,
                    )
                )
                continue

            try:
                converted = self._convert_value(target, raw_value, conversion_options)
            except _MaterializationError as error:
                self._add_error(
                    result,
                    code=error.code,
                    message=error.message,
                    source_header=source_key,
                    target_attribute_id=target.id,
                    context=error.context,
                )
                result.fields.append(
                    CsvMaterializedField(
                        source_header=source_key,
                        target_attribute_id=target.id,
                        target_key=target_key,
                        conversion_succeeded=False,
                    )
                )
                continue

            result.record_values[target_key] = converted
            result.fields.append(
                CsvMaterializedField(
                    source_header=source_key,
                    target_attribute_id=target.id,
                    target_key=target_key,
                    value=converted,
                    conversion_succeeded=True,
                )
            )

        result.eligible_to_proceed = not result.errors
        return result

    @staticmethod
    def _copy_targets(
        target_attributes: Sequence[
            CsvMaterializationTargetAttribute | CsvImportTargetAttribute
        ],
    ) -> list[CsvMaterializationTargetAttribute]:
        return [
            CsvMaterializationTargetAttribute.model_validate(
                target.model_dump(mode="python")
            )
            for target in target_attributes
        ]

    @staticmethod
    def _resolve_source_cell(
        source_cells: Mapping[str, str], source_header: str
    ) -> tuple[str, str, str | None]:
        if source_header in source_cells:
            return source_header, source_cells[source_header], None

        normalized = normalize_csv_header(source_header)
        matches = [
            (key, value)
            for key, value in source_cells.items()
            if normalize_csv_header(key) == normalized
        ]
        if len(matches) == 1:
            return matches[0][0], matches[0][1], None
        if len(matches) > 1:
            return source_header, "", "AMBIGUOUS_SOURCE_COLUMN"
        return source_header, "", "MISSING_MAPPED_SOURCE_COLUMN"

    def _convert_value(
        self,
        target: CsvMaterializationTargetAttribute,
        raw_value: str,
        options: CsvMaterializationOptions,
    ) -> Any:
        attribute_type = target.attribute_type
        if raw_value == "":
            return self._blank_value(attribute_type)
        if target.importable is False or attribute_type in UNSUPPORTED_TYPES:
            raise _MaterializationError(
                "UNSUPPORTED_ATTRIBUTE_TYPE",
                "Attribute type is deferred because its safe import representation is undefined.",
                {"attribute_type": attribute_type},
            )
        if attribute_type in TEXT_LIKE_TYPES:
            return raw_value
        if attribute_type in NUMERIC_TYPES:
            return self._convert_number(raw_value)
        if attribute_type == "checkbox":
            return self._convert_boolean(raw_value)
        if attribute_type == "date":
            return self._convert_date(raw_value)
        if attribute_type in {"timestamp", "datetime"}:
            return self._convert_datetime(raw_value)
        if attribute_type in SELECT_TYPES:
            return self._convert_select(raw_value, target)
        if attribute_type == "multi_select":
            return self._convert_multi_select(raw_value, target, options)
        raise _MaterializationError(
            "UNSUPPORTED_ATTRIBUTE_TYPE",
            "Attribute type is not supported by deterministic row materialization.",
            {"attribute_type": attribute_type},
        )

    @staticmethod
    def _blank_value(attribute_type: str) -> Any:
        if attribute_type in TEXT_LIKE_TYPES or attribute_type in SELECT_TYPES:
            return ""
        if attribute_type == "multi_select":
            return []
        if attribute_type in NUMERIC_TYPES or attribute_type in {"checkbox", "date", "timestamp", "datetime"}:
            return None
        raise _MaterializationError(
            "UNSUPPORTED_ATTRIBUTE_TYPE",
            "Blank values are not materialized for deferred attribute types.",
            {"attribute_type": attribute_type},
        )

    @staticmethod
    def _convert_number(raw_value: str) -> int | float:
        if raw_value.casefold() in {"nan", "+nan", "-nan", "infinity", "+infinity", "-infinity"}:
            raise _MaterializationError("NON_FINITE_NUMBER", "Mapped number must be finite.")
        if not NUMERIC_PATTERN.fullmatch(raw_value):
            raise _MaterializationError("INVALID_NUMBER", "Mapped value is not a valid number.")
        try:
            decimal_value = Decimal(raw_value)
        except InvalidOperation as error:
            raise _MaterializationError("INVALID_NUMBER", "Mapped value is not a valid number.") from error
        if not decimal_value.is_finite():
            raise _MaterializationError("NON_FINITE_NUMBER", "Mapped number must be finite.")
        if decimal_value == decimal_value.to_integral_value():
            return int(decimal_value)
        float_value = float(decimal_value)
        if not math.isfinite(float_value):
            raise _MaterializationError("NON_FINITE_NUMBER", "Mapped number must be finite.")
        return float_value

    @staticmethod
    def _convert_boolean(raw_value: str) -> bool:
        if raw_value == "true":
            return True
        if raw_value == "false":
            return False
        raise _MaterializationError(
            "INVALID_BOOLEAN",
            "Boolean values must be exactly 'true' or 'false'.",
        )

    @staticmethod
    def _convert_date(raw_value: str) -> str:
        if not DATE_PATTERN.fullmatch(raw_value):
            raise _MaterializationError("INVALID_DATE", "Date must use YYYY-MM-DD format.")
        try:
            return date.fromisoformat(raw_value).isoformat()
        except ValueError as error:
            raise _MaterializationError("INVALID_DATE", "Mapped value is not a valid date.") from error

    @staticmethod
    def _convert_datetime(raw_value: str) -> str:
        if "T" not in raw_value or raw_value.startswith("T"):
            raise _MaterializationError(
                "INVALID_DATETIME", "Datetime must use an ISO date-time with a T separator."
            )
        try:
            datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError as error:
            raise _MaterializationError("INVALID_DATETIME", "Mapped value is not a valid datetime.") from error
        return raw_value

    def _convert_select(
        self, raw_value: str, target: CsvMaterializationTargetAttribute
    ) -> str:
        options = self._get_options(target)
        if not options:
            raise _MaterializationError(
                "UNSUPPORTED_ATTRIBUTE_TYPE",
                "Select values require authoritative target options.",
                {"attribute_type": target.attribute_type},
            )
        return self._match_option(raw_value, options)

    def _convert_multi_select(
        self,
        raw_value: str,
        target: CsvMaterializationTargetAttribute,
        options: CsvMaterializationOptions,
    ) -> list[str]:
        delimiter = options.multi_select_delimiter
        if not delimiter:
            raise _MaterializationError(
                "UNSUPPORTED_ATTRIBUTE_TYPE",
                "Multi-select conversion requires an explicit delimiter option.",
                {"attribute_type": target.attribute_type},
            )
        tokens = raw_value.split(delimiter)
        if any(not token.strip() for token in tokens):
            raise _MaterializationError(
                "INVALID_MULTI_SELECT", "Multi-select value contains an empty option."
            )
        target_options = self._get_options(target)
        if not target_options:
            raise _MaterializationError(
                "UNSUPPORTED_ATTRIBUTE_TYPE",
                "Multi-select values require authoritative target options.",
                {"attribute_type": target.attribute_type},
            )
        try:
            return [self._match_option(token.strip(), target_options) for token in tokens]
        except _MaterializationError as error:
            if error.code == "UNKNOWN_SELECT_OPTION":
                error.code = "INVALID_MULTI_SELECT"
            raise

    @staticmethod
    def _get_options(target: CsvMaterializationTargetAttribute) -> list[tuple[str, str]]:
        raw_options = target.config.get("options") or target.config.get("statuses")
        if not isinstance(raw_options, list):
            return []
        options: list[tuple[str, str]] = []
        for option in raw_options:
            if isinstance(option, (str, int, float)):
                value = label = str(option)
            elif isinstance(option, dict):
                value_source = option.get("value", option.get("label"))
                label_source = option.get("label", option.get("value"))
                if value_source is None or label_source is None:
                    continue
                value, label = str(value_source), str(label_source)
            else:
                continue
            options.append((value, label))
        return options

    @staticmethod
    def _match_option(raw_value: str, options: Sequence[tuple[str, str]]) -> str:
        normalized = raw_value.strip().casefold()
        matches = {
            value
            for value, label in options
            if value.strip().casefold() == normalized or label.strip().casefold() == normalized
        }
        if not matches:
            raise _MaterializationError(
                "UNKNOWN_SELECT_OPTION", "Mapped value does not match a target option."
            )
        if len(matches) > 1:
            raise _MaterializationError(
                "AMBIGUOUS_SELECT_OPTION",
                "Mapped value matches multiple target options.",
            )
        return next(iter(matches))

    @staticmethod
    def _add_error(
        result: CsvRowMaterializationResult,
        *,
        code: str,
        message: str,
        source_header: str | None = None,
        target_attribute_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        result.errors.append(
            CsvPreflightIssue(
                code=code,
                message=message,
                row_number=result.source_row_number,
                source_header=source_header,
                target_attribute_id=target_attribute_id,
                context=context or {},
            )
        )


__all__ = ["CsvImportMaterializationService"]
