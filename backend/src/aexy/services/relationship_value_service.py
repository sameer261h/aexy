"""Deterministic relationship-value normalization and diff engine.

Pure functions with no database or I/O. Accept existing and requested
relationship values alongside cardinality metadata and return a typed
normalization result.

All types are defined inline to avoid the ``aexy.schemas.__init__`` import
chain, which pulls in every model dependency unnecessarily.  Future
integration can move the types into a shared schemas module once that
module supports fine-grained imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal
from uuid import UUID


# =============================================================================
# Schema types (inline to avoid aexy.schemas.__init__ transitive deps)
# =============================================================================

class RelationshipErrorCode(str, Enum):
    INVALID_RELATIONSHIP_VALUE = "invalid_relationship_value"
    INVALID_IDENTIFIER = "invalid_identifier"
    BLANK_IDENTIFIER = "blank_identifier"
    DUPLICATE_IDENTIFIER = "duplicate_identifier"
    CARDINALITY_EXCEEDED = "cardinality_exceeded"
    UNSUPPORTED_REPRESENTATION = "unsupported_relationship_representation"


class RelationshipWarningCode(str, Enum):
    DUPLICATES_REMOVED = "duplicates_removed"
    ORDER_CHANGED = "order_changed"
    LEGACY_FORMAT_NORMALIZED = "legacy_format_normalized"


@dataclass(slots=True)
class RelationshipError:
    code: RelationshipErrorCode
    message: str
    identifier: str | None = None
    position: int | None = None
    cardinality: Literal["single", "multi"] | None = None


@dataclass(slots=True)
class RelationshipWarning:
    code: RelationshipWarningCode
    message: str
    identifier: str | None = None


@dataclass(slots=True)
class RelationshipNormalizationResult:
    normalized_existing: list[str] | None
    normalized_requested: list[str] | None
    to_add: list[str]
    to_remove: list[str]
    unchanged: list[str]
    membership_changed: bool
    order_changed: bool
    is_noop: bool
    errors: list[RelationshipError] = field(default_factory=list)
    warnings: list[RelationshipWarning] = field(default_factory=list)


# =============================================================================
# Normalization engine
# =============================================================================

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _normalize_raw_value(raw: Any) -> list[str] | None:
    """Convert a raw relationship value into a list of items for validation.

    Returns ``None`` for ``None`` and empty-string.
    Non-string items are passed through to validation (not stringified or
    coerced).  ``uuid.UUID`` objects and arbitrary types are rejected by
    ``_validate_and_deduplicate``.
    Raises ``ValueError`` when the top-level value type is unsupported.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, list):
        result: list[str] = []
        for item in raw:
            if item is None:
                continue
            result.append(item)
        return result if result else None
    if isinstance(raw, str):
        return [raw]
    raise ValueError(f"unsupported relationship value type: {type(raw).__name__}")


def _validate_and_deduplicate(
    identifiers: list[str],
    cardinality: str,
) -> tuple[list[str], list[RelationshipError], list[RelationshipWarning]]:
    errors: list[RelationshipError] = []
    warnings: list[RelationshipWarning] = []
    seen: set[str] = set()
    deduped: list[str] = []

    for idx, raw_id in enumerate(identifiers):
        stripped = raw_id.strip() if isinstance(raw_id, str) else raw_id

        if isinstance(stripped, str) and stripped == "":
            errors.append(RelationshipError(
                code=RelationshipErrorCode.BLANK_IDENTIFIER,
                message="blank identifier is not allowed",
                identifier="",
                position=idx,
                cardinality=cardinality,
            ))
            continue

        if not isinstance(stripped, str) or not _is_valid_uuid(stripped):
            errors.append(RelationshipError(
                code=RelationshipErrorCode.INVALID_IDENTIFIER,
                message=f"invalid record identifier: {raw_id!r}",
                identifier=str(raw_id),
                position=idx,
                cardinality=cardinality,
            ))
            continue

        if stripped in seen:
            warnings.append(RelationshipWarning(
                code=RelationshipWarningCode.DUPLICATES_REMOVED,
                message=f"duplicate identifier removed: {stripped}",
                identifier=stripped,
            ))
            continue

        seen.add(stripped)
        deduped.append(stripped)

    return deduped, errors, warnings


def normalize_relationship_value(
    existing_value: Any,
    requested_value: Any,
    *,
    allow_multiple: bool = False,
) -> RelationshipNormalizationResult:
    """Normalize existing and requested relationship values and compute the diff.

    Args:
        existing_value: The current relationship value from record data.
            May be ``None``, a single UUID string, or a list of UUID strings.
        requested_value: The new relationship value. Same representations.
        allow_multiple: When ``True`` the relationship accepts multiple
            identifiers (multi cardinality). When ``False`` only zero or
            one identifier is accepted (single cardinality).

    Returns:
        A ``RelationshipNormalizationResult`` containing normalised values,
        diff results, and any validation errors or warnings.

    The function is pure: inputs are never mutated.
    """
    errors: list[RelationshipError] = []
    warnings: list[RelationshipWarning] = []

    cardinality = "multi" if allow_multiple else "single"

    try:
        norm_existing_raw = _normalize_raw_value(existing_value)
    except ValueError as exc:
        return RelationshipNormalizationResult(
            normalized_existing=None, normalized_requested=None,
            to_add=[], to_remove=[], unchanged=[],
            membership_changed=False, order_changed=False, is_noop=False,
            errors=[RelationshipError(
                code=RelationshipErrorCode.INVALID_RELATIONSHIP_VALUE,
                message=str(exc),
            )],
        )

    try:
        norm_requested_raw = _normalize_raw_value(requested_value)
    except ValueError as exc:
        return RelationshipNormalizationResult(
            normalized_existing=None, normalized_requested=None,
            to_add=[], to_remove=[], unchanged=[],
            membership_changed=False, order_changed=False, is_noop=False,
            errors=[RelationshipError(
                code=RelationshipErrorCode.INVALID_RELATIONSHIP_VALUE,
                message=str(exc),
            )],
        )

    if norm_existing_raw is not None:
        norm_existing_raw, e, w = _validate_and_deduplicate(norm_existing_raw, cardinality)
        errors.extend(e)
        warnings.extend(w)

    if norm_requested_raw is not None:
        norm_requested_raw, e, w = _validate_and_deduplicate(norm_requested_raw, cardinality)
        errors.extend(e)
        warnings.extend(w)

    if not allow_multiple and norm_requested_raw is not None and len(norm_requested_raw) > 1:
        errors.append(RelationshipError(
            code=RelationshipErrorCode.CARDINALITY_EXCEEDED,
            message=(
                "single-cardinality relationship accepts at most one "
                f"identifier, got {len(norm_requested_raw)}"
            ),
            cardinality="single",
        ))

    if errors:
        return RelationshipNormalizationResult(
            normalized_existing=norm_existing_raw,
            normalized_requested=norm_requested_raw,
            to_add=[], to_remove=[], unchanged=[],
            membership_changed=False, order_changed=False, is_noop=False,
            errors=errors, warnings=warnings,
        )

    existing_set = set(norm_existing_raw or [])
    requested_set = set(norm_requested_raw or [])

    to_add: list[str] = []
    to_remove: list[str] = []
    unchanged: list[str] = []

    if norm_requested_raw:
        for rid in norm_requested_raw:
            if rid not in existing_set:
                to_add.append(rid)
            else:
                unchanged.append(rid)

    if norm_existing_raw:
        for rid in norm_existing_raw:
            if rid not in requested_set:
                to_remove.append(rid)

    membership_changed = bool(to_add or to_remove)

    order_changed = False
    if not membership_changed and norm_existing_raw and norm_requested_raw:
        order_changed = norm_existing_raw != norm_requested_raw
        if order_changed:
            warnings.append(RelationshipWarning(
                code=RelationshipWarningCode.ORDER_CHANGED,
                message="ordering changed without membership changes",
            ))

    is_noop = not membership_changed and not order_changed

    return RelationshipNormalizationResult(
        normalized_existing=norm_existing_raw,
        normalized_requested=norm_requested_raw,
        to_add=to_add, to_remove=to_remove, unchanged=unchanged,
        membership_changed=membership_changed, order_changed=order_changed,
        is_noop=is_noop, errors=errors, warnings=warnings,
    )
