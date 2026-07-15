"""US-1.5 palette honesty trim: the builder palette must only offer CRM triggers
and actions that actually execute, while the underlying type ids stay valid for
validation and already-saved automations."""

from aexy.schemas.automation import (
    get_triggers_for_module,
    get_actions_for_module,
    get_trigger_ids,
    get_action_ids,
    PALETTE_HIDDEN_TRIGGERS,
    PALETTE_HIDDEN_ACTIONS,
)

# The only CRM triggers with a real dispatch path today.
LIVE_CRM_TRIGGERS = {
    "record.created",
    "record.updated",
    "record.deleted",
    "field.changed",
    "stage.changed",
}

# CRM actions with a real handler in the live (linear) executor.
LIVE_CRM_ACTIONS = {
    "send_email",
    "send_slack",
    "webhook_call",
    "run_agent",
    "create_task",
    "notify_user",
    "notify_team",
    "create_record",
    "update_record",
    "add_to_list",
    "remove_from_list",
    "enroll_in_sequence",
}

# Shells / unwired nodes that must NOT appear in the palette.
HIDDEN_CRM_TRIGGERS = PALETTE_HIDDEN_TRIGGERS["crm"]
HIDDEN_CRM_ACTIONS = PALETTE_HIDDEN_ACTIONS["common"] | PALETTE_HIDDEN_ACTIONS["crm"]


def test_palette_triggers_hide_unwired_and_keep_live():
    palette = {t["id"] for t in get_triggers_for_module("crm")}
    # every hidden trigger is gone from the palette
    assert palette.isdisjoint(HIDDEN_CRM_TRIGGERS)
    # every live trigger is still offered
    assert LIVE_CRM_TRIGGERS <= palette
    # concretely: the never-firing ones are gone
    assert "schedule.daily" not in palette
    assert "form.submitted" not in palette
    assert "email.opened" not in palette


def test_palette_actions_hide_shells_and_keep_live():
    palette = {a["id"] for a in get_actions_for_module("crm")}
    assert palette.isdisjoint(HIDDEN_CRM_ACTIONS)
    assert LIVE_CRM_ACTIONS <= palette
    # concretely: the shell actions are gone
    assert "send_sms" not in palette
    assert "delete_record" not in palette
    assert "enrich_record" not in palette
    # ...and the real ones remain
    assert "send_email" in palette
    assert "create_record" in palette


def test_hidden_ids_stay_valid_for_validation():
    """Hiding from the palette must NOT remove the ids from the membership
    helpers — validation and existing automations still recognize them."""
    trigger_ids = set(get_trigger_ids("crm"))
    action_ids = set(get_action_ids("crm"))
    assert HIDDEN_CRM_TRIGGERS <= trigger_ids
    assert HIDDEN_CRM_ACTIONS <= action_ids


def test_other_modules_unaffected():
    """The trim is CRM-scoped; other modules keep their full trigger list."""
    ticket_palette = {t["id"] for t in get_triggers_for_module("tickets")}
    assert "ticket.created" in ticket_palette
    assert len(ticket_palette) == len(get_trigger_ids("tickets"))
