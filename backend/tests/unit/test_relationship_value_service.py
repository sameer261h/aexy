"""Unit tests for relationship value normalization and diff engine.

Avoids the ``aexy.services.__init__`` blanket import chain by
importing the module directly via ``importlib``.
"""

import importlib.util
import sys
from uuid import uuid4

_MODULE_PATH = "src/aexy/services/relationship_value_service.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "relationship_value_service", _MODULE_PATH
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["relationship_value_service"] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()
normalize_relationship_value = _mod.normalize_relationship_value
RelationshipErrorCode = _mod.RelationshipErrorCode
RelationshipWarningCode = _mod.RelationshipWarningCode


def _uid() -> str:
    return str(uuid4())


# --- Empty / null / absent ----------------------------------------------------

def test_empty_existing_and_empty_requested_noop():
    result = normalize_relationship_value(None, None)
    assert result.is_noop
    assert result.normalized_existing is None
    assert result.normalized_requested is None
    assert result.to_add == []
    assert result.to_remove == []
    assert not result.membership_changed
    assert not result.order_changed
    assert result.errors == []


def test_null_existing_and_null_requested_noop():
    result = normalize_relationship_value(None, None)
    assert result.is_noop


def test_empty_string_treated_as_absent():
    result = normalize_relationship_value("", "")
    assert result.normalized_existing is None
    assert result.normalized_requested is None
    assert result.is_noop


# --- Addition -----------------------------------------------------------------

def test_one_new_valid_identifier_adds_one():
    rid = _uid()
    result = normalize_relationship_value(None, rid)
    assert result.to_add == [rid]
    assert result.to_remove == []
    assert result.membership_changed
    assert result.errors == []


def test_one_new_valid_identifier_single_cardinality():
    rid = _uid()
    result = normalize_relationship_value(None, rid, allow_multiple=False)
    assert result.to_add == [rid]
    assert result.errors == []


# --- Removal ------------------------------------------------------------------

def test_removing_one_identifier_produces_one_removal():
    rid = _uid()
    result = normalize_relationship_value([rid], None)
    assert result.to_remove == [rid]
    assert result.to_add == []
    assert result.membership_changed


def test_removing_one_identifier_from_list():
    rid = _uid()
    result = normalize_relationship_value([rid], [])
    assert result.to_remove == [rid]


# --- Replacement --------------------------------------------------------------

def test_replacing_one_identifier():
    rid_a = _uid()
    rid_b = _uid()
    result = normalize_relationship_value(rid_a, rid_b)
    assert result.to_add == [rid_b]
    assert result.to_remove == [rid_a]
    assert result.membership_changed


# --- Multiple additions preserve order ----------------------------------------

def test_multiple_additions_preserve_requested_order():
    a, b, c = _uid(), _uid(), _uid()
    result = normalize_relationship_value(None, [a, b, c], allow_multiple=True)
    assert result.to_add == [a, b, c]
    assert result.unchanged == []


# --- Multiple removals preserve existing order --------------------------------

def test_multiple_removals_preserve_existing_order():
    a, b, c = _uid(), _uid(), _uid()
    result = normalize_relationship_value([a, b, c], None)
    assert result.to_remove == [a, b, c]


# --- Unchanged ----------------------------------------------------------------

def test_unchanged_identifiers_identified_correctly():
    a, b, c = _uid(), _uid(), _uid()
    d = _uid()
    result = normalize_relationship_value([a, b, c], [a, c, d], allow_multiple=True)
    assert set(result.unchanged) == {a, c}
    assert set(result.to_add) == {d}
    assert set(result.to_remove) == {b}


# --- Identical values ---------------------------------------------------------

def test_identical_single_value_noop():
    rid = _uid()
    result = normalize_relationship_value(rid, rid)
    assert result.is_noop


def test_identical_list_noop():
    rids = [_uid(), _uid(), _uid()]
    result = normalize_relationship_value(rids, rids, allow_multiple=True)
    assert result.is_noop


# --- Reordering ---------------------------------------------------------------

def test_reordering_without_membership_change_detected():
    a, b, c = _uid(), _uid(), _uid()
    result = normalize_relationship_value([a, b, c], [c, a, b], allow_multiple=True)
    assert not result.membership_changed
    assert result.order_changed
    assert not result.is_noop
    assert any(w.code == RelationshipWarningCode.ORDER_CHANGED for w in result.warnings)


def test_reordering_produces_order_changed_warning():
    a, b = _uid(), _uid()
    result = normalize_relationship_value([a, b], [b, a], allow_multiple=True)
    assert result.order_changed
    assert any(w.code == RelationshipWarningCode.ORDER_CHANGED for w in result.warnings)


# --- Duplicate handling (deduplicate with warning) ----------------------------

def test_duplicate_identifiers_deduplicated_with_warning():
    rid = _uid()
    result = normalize_relationship_value(None, [rid, rid, rid])
    assert result.normalized_requested == [rid]
    assert result.to_add == [rid]
    dup_warnings = [w for w in result.warnings if w.code == RelationshipWarningCode.DUPLICATES_REMOVED]
    assert len(dup_warnings) == 2


def test_duplicates_do_not_create_duplicate_diff_entries():
    rid = _uid()
    result = normalize_relationship_value(None, [rid, rid])
    assert result.to_add == [rid]
    assert len(result.to_add) == 1


def test_existing_duplicates_handled():
    rid = _uid()
    result = normalize_relationship_value([rid, rid], [rid])
    assert result.normalized_existing == [rid]
    assert result.is_noop


# --- Invalid identifier type --------------------------------------------------

def test_invalid_identifier_type_rejected():
    result = normalize_relationship_value(None, [123])
    assert any(e.code == RelationshipErrorCode.INVALID_IDENTIFIER for e in result.errors)


def test_uuid_object_rejected():
    """uuid.UUID objects are not accepted — strings only per source contract."""
    import uuid as _uuid_mod
    uid = _uuid_mod.uuid4()
    result = normalize_relationship_value(None, [uid])
    assert any(e.code == RelationshipErrorCode.INVALID_IDENTIFIER for e in result.errors)


def test_arbitrary_object_rejected():
    """Arbitrary objects are rejected even when __str__ resembles a UUID."""
    class FakeID:
        def __str__(self):
            return "12345678-1234-1234-1234-123456789abc"
    result = normalize_relationship_value(None, [FakeID()])
    assert any(e.code == RelationshipErrorCode.INVALID_IDENTIFIER for e in result.errors)


def test_mixed_valid_and_invalid_requested():
    """Mixed valid/invalid values: errors reported, valid IDs normalized but diff withheld."""
    uid = _uid()
    result = normalize_relationship_value(None, ["", uid, "bad"], allow_multiple=True)
    codes = [e.code for e in result.errors]
    assert RelationshipErrorCode.BLANK_IDENTIFIER in codes
    assert RelationshipErrorCode.INVALID_IDENTIFIER in codes
    assert uid in (result.normalized_requested or [])
    assert result.to_add == []  # diff withheld when errors present


def test_malformed_existing_value_flagged():
    """Malformed existing value produces errors and no diff."""
    uid = _uid()
    result = normalize_relationship_value(["bad-id"], [uid])
    assert any(e.code == RelationshipErrorCode.INVALID_IDENTIFIER for e in result.errors)
    assert result.to_add == []
    assert result.to_remove == []


def test_malformed_requested_value_flagged():
    """Malformed requested value produces errors and no diff."""
    uid = _uid()
    result = normalize_relationship_value([uid], ["bad-id"])
    assert any(e.code == RelationshipErrorCode.INVALID_IDENTIFIER for e in result.errors)
    assert result.to_add == []
    assert result.to_remove == []


def test_malformed_both_values_flagged():
    """Malformed in both values produces errors for both."""
    result = normalize_relationship_value(["bad"], ["also-bad"])
    assert len(result.errors) == 2


def test_non_uuid_string_rejected():
    result = normalize_relationship_value(None, "not-a-uuid")
    assert any(e.code == RelationshipErrorCode.INVALID_IDENTIFIER for e in result.errors)


# --- Invalid identifier format ------------------------------------------------

def test_invalid_uuid_format_rejected():
    result = normalize_relationship_value(None, "xyz-123")
    assert any(e.code == RelationshipErrorCode.INVALID_IDENTIFIER for e in result.errors)


def test_valid_uuid_accepted():
    rid = _uid()
    result = normalize_relationship_value(None, rid)
    assert result.errors == []


# --- Blank identifier ---------------------------------------------------------

def test_blank_identifier_rejected():
    result = normalize_relationship_value(None, ["  ", _uid()])
    assert any(e.code == RelationshipErrorCode.BLANK_IDENTIFIER for e in result.errors)


# --- Unsupported value type ---------------------------------------------------

def test_unsupported_value_type_rejected():
    result = normalize_relationship_value(None, {"id": "x"})
    assert any(e.code == RelationshipErrorCode.INVALID_RELATIONSHIP_VALUE for e in result.errors)


# --- Single cardinality -------------------------------------------------------

def test_single_cardinality_accepts_zero():
    result = normalize_relationship_value(None, None, allow_multiple=False)
    assert result.errors == []
    assert result.is_noop


def test_single_cardinality_accepts_one():
    result = normalize_relationship_value(None, _uid(), allow_multiple=False)
    assert result.errors == []


def test_single_cardinality_rejects_multiple():
    result = normalize_relationship_value(None, [_uid(), _uid()], allow_multiple=False)
    assert any(e.code == RelationshipErrorCode.CARDINALITY_EXCEEDED for e in result.errors)


# --- Multi cardinality --------------------------------------------------------

def test_multi_cardinality_accepts_zero():
    result = normalize_relationship_value(None, None, allow_multiple=True)
    assert result.errors == []
    assert result.is_noop


def test_multi_cardinality_accepts_one():
    result = normalize_relationship_value(None, _uid(), allow_multiple=True)
    assert result.errors == []


def test_multi_cardinality_accepts_several():
    result = normalize_relationship_value(None, [_uid(), _uid(), _uid()], allow_multiple=True)
    assert result.errors == []


# --- Input immutability -------------------------------------------------------

def test_existing_input_not_mutated():
    rids = [_uid(), _uid()]
    original = list(rids)
    normalize_relationship_value(rids, None)
    assert rids == original


def test_requested_input_not_mutated():
    rids = [_uid(), _uid()]
    original = list(rids)
    normalize_relationship_value(None, rids)
    assert rids == original


# --- Error ordering deterministic ---------------------------------------------

def test_error_ordering_deterministic():
    result = normalize_relationship_value(None, ["", "bad", _uid()])
    codes = [e.code for e in result.errors]
    assert codes == [
        RelationshipErrorCode.BLANK_IDENTIFIER,
        RelationshipErrorCode.INVALID_IDENTIFIER,
    ]


# --- Diff ordering deterministic ----------------------------------------------

def test_addition_ordering_follows_requested():
    a, b, c = _uid(), _uid(), _uid()
    result = normalize_relationship_value(None, [c, a, b], allow_multiple=True)
    assert result.to_add == [c, a, b]


def test_removal_ordering_follows_existing():
    a, b, c = _uid(), _uid(), _uid()
    result = normalize_relationship_value([c, a, b], None)
    assert result.to_remove == [c, a, b]


# --- No database / external access --------------------------------------------

def test_no_database_access():
    import inspect
    source = inspect.getsource(normalize_relationship_value)
    assert "Session" not in source
    assert "engine" not in source
    assert "db" not in source
    assert "select(" not in source
    assert "http" not in source.lower()


# --- Legacy empty-list normalizes to absent -----------------------------------

def test_empty_list_normalizes_to_absent():
    result = normalize_relationship_value([], [])
    assert result.normalized_existing is None
    assert result.normalized_requested is None
    assert result.is_noop
