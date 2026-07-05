"""Security invariants for activity-feed role scoping.

The feed is filtered per-role by mapping each activity entity_type to the app
that gates it. If a new EntityType is added without a mapping, it would bypass
the filter and leak to every role — these tests fail loudly if that happens.
"""

from typing import get_args

from aexy.api.entity_activity import (
    ADMIN_ONLY_ENTITY_TYPES,
    ENTITY_TYPE_TO_APP,
)
from aexy.models.app_definitions import APP_CATALOG
from aexy.schemas.entity_activity import EntityType


def test_every_entity_type_is_gated():
    """No entity_type may be ungated (that would leak to all roles)."""
    all_types = set(get_args(EntityType))
    gated = set(ENTITY_TYPE_TO_APP) | set(ADMIN_ONLY_ENTITY_TYPES)
    assert all_types - gated == set(), "ungated entity types leak to every role"


def test_no_stale_mapping_keys():
    mapped = set(ENTITY_TYPE_TO_APP) | set(ADMIN_ONLY_ENTITY_TYPES)
    assert mapped - set(get_args(EntityType)) == set()


def test_mapped_apps_exist_in_catalog():
    bad = {a for a in ENTITY_TYPE_TO_APP.values() if a not in APP_CATALOG}
    assert bad == set(), f"mapping references unknown apps: {bad}"


def test_hr_and_admin_types_are_admin_only():
    # These have no user-facing app gate and must never be app-mapped (which
    # would make them visible to any role with that app).
    for et in ("leave_request", "leave_policy", "role"):
        assert et in ADMIN_ONLY_ENTITY_TYPES
        assert et not in ENTITY_TYPE_TO_APP


def test_hiring_requirement_gated_by_hiring_app():
    assert ENTITY_TYPE_TO_APP.get("hiring_requirement") == "hiring"
