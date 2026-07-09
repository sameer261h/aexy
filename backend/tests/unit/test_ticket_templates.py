"""Invariants for the pre-built ticket form templates.

These lock in the conventions documented on ``FORM_TEMPLATES`` so the catalog
can't silently drift again (the original bug: templates carried an ``email``
field that duplicated the public form's built-in contact section).
"""
import pytest

from aexy.models.ticketing import TicketFieldType, TicketFormTemplateType
from aexy.services.ticket_form_service import FORM_TEMPLATES

VALID_FIELD_TYPES = {t.value for t in TicketFieldType}
VALID_TEMPLATE_KEYS = {t.value for t in TicketFormTemplateType}


def test_templates_registered_in_enums():
    """Every template key is a valid TicketFormTemplateType (schema validates it)."""
    for key in FORM_TEMPLATES:
        assert key in VALID_TEMPLATE_KEYS, f"{key} missing from TicketFormTemplateType enum"


@pytest.mark.parametrize("key", list(FORM_TEMPLATES))
def test_template_has_display_metadata(key):
    t = FORM_TEMPLATES[key]
    assert t.get("name")
    assert t.get("description")
    assert t.get("icon"), f"{key} missing icon"
    assert t.get("color"), f"{key} missing color"
    assert t.get("category"), f"{key} missing category"
    assert t.get("fields"), f"{key} has no fields"


@pytest.mark.parametrize("key", list(FORM_TEMPLATES))
def test_no_contact_fields_in_templates(key):
    """Contact info comes from the built-in section; templates must not repeat it."""
    for f in FORM_TEMPLATES[key]["fields"]:
        assert f["field_type"] != "email", f"{key}.{f['field_key']} is an email field"
        assert f["field_key"] not in ("email", "name"), f"{key} has a contact field {f['field_key']}"


@pytest.mark.parametrize("key", list(FORM_TEMPLATES))
def test_file_fields_use_attachments_convention(key):
    for f in FORM_TEMPLATES[key]["fields"]:
        if f["field_type"] == "file":
            assert f["field_key"] == "attachments", (
                f"{key} file field uses key {f['field_key']!r}, expected 'attachments'"
            )


@pytest.mark.parametrize("key", list(FORM_TEMPLATES))
def test_attachment_field_is_last_when_present(key):
    fields = FORM_TEMPLATES[key]["fields"]
    file_idxs = [i for i, f in enumerate(fields) if f["field_type"] == "file"]
    assert len(file_idxs) <= 1, f"{key} has more than one file field"
    if file_idxs:
        assert file_idxs[0] == len(fields) - 1, f"{key} attachment field is not last"


@pytest.mark.parametrize("key", list(FORM_TEMPLATES))
def test_all_field_types_valid_and_first_field_is_title(key):
    fields = FORM_TEMPLATES[key]["fields"]
    for f in fields:
        assert f["field_type"] in VALID_FIELD_TYPES, f"{key}.{f['field_key']} bad type {f['field_type']}"
        assert f.get("field_key"), f"{key} has a field with no key"
    assert fields[0]["field_key"] == "title", f"{key} does not lead with a title field"
