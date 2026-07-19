"""Phase-2 palette honesty trim (US-1.5): the automation registry is CRM-only.

Non-CRM modules are descoped (see prds/automations-noncrm-deferred.md) and
orphan/unwired CRM capabilities are hidden until wired/built. The registry
accessors are the source of truth the frontend palette consumes.
"""

from aexy.schemas.automation import (
    get_action_ids,
    get_actions_for_module,
    get_all_actions,
    get_all_triggers,
    get_trigger_ids,
    get_triggers_for_module,
)

NON_CRM_MODULES = [
    "tickets", "hiring", "email_marketing", "uptime",
    "sprints", "forms", "booking", "tracking", "compliance",
]
HIDDEN_CRM_TRIGGERS = [
    "schedule.daily", "schedule.weekly", "date.approaching", "date.passed",
    "webhook.received", "email.opened", "email.clicked", "email.replied",
    # 2026-07-19 trim: no emitter, or emitted against another module.
    "list_entry.added", "list_entry.removed", "status.changed",
    "form.submitted",
]
ORPHAN_ACTIONS = ["api_request", "enrich_record", "classify_record", "generate_summary"]
# 2026-07-19 trim: no case in the published executor, so each of these would
# be recorded as a successful step while doing nothing at all.
UNRUNNABLE_ACTIONS = [
    "send_sms", "delete_record", "link_records", "remove_from_sequence",
    "wait", "condition",
    # Config-key mismatch rather than a missing handler: the panel and the
    # published executor disagree on field names, so it never fires and the
    # step is still recorded as successful.
    "webhook_call",
]
# Withheld by product decision rather than by a missing handler.
WITHHELD_ACTIONS = [
    "add_to_list", "remove_from_list", "enroll_in_sequence", "run_agent",
]


# --- module scoping -------------------------------------------------------

def test_all_triggers_only_crm():
    modules = set(get_all_triggers().keys())
    assert modules == {"crm"}


def test_all_actions_only_crm_and_common():
    modules = set(get_all_actions().keys())
    assert modules == {"common", "crm"}


def test_non_crm_module_triggers_empty():
    for module in NON_CRM_MODULES:
        assert get_triggers_for_module(module) == [], module
        assert get_trigger_ids(module) == [], module


def test_non_crm_module_actions_empty():
    for module in NON_CRM_MODULES:
        assert get_actions_for_module(module) == [], module
        assert get_action_ids(module) == [], module


# --- hidden CRM capabilities ---------------------------------------------

def test_hidden_crm_triggers_removed():
    ids = get_trigger_ids("crm")
    for trig in HIDDEN_CRM_TRIGGERS:
        assert trig not in ids, trig


def test_orphan_actions_removed():
    ids = get_action_ids("crm")
    for act in ORPHAN_ACTIONS:
        assert act not in ids, act


def test_actions_without_an_executor_case_removed():
    """These reach the executor's catch-all, which reports success.

    Offering them means an automation that silently does nothing while its
    run history claims every step passed.
    """
    ids = get_action_ids("crm")
    for act in UNRUNNABLE_ACTIONS:
        assert act not in ids, act


def test_withheld_actions_removed():
    ids = get_action_ids("crm")
    for act in WITHHELD_ACTIONS:
        assert act not in ids, act


# --- core CRM capabilities preserved -------------------------------------

def test_crm_core_triggers_preserved():
    ids = get_trigger_ids("crm")
    for trig in ["record.created", "record.updated", "field.changed",
                 "stage.changed"]:
        assert trig in ids, trig


def test_crm_triggers_are_exactly_the_agreed_set():
    """Pin the whole list: a new registry entry must be an explicit decision."""
    assert set(get_trigger_ids("crm")) == {
        "record.created", "record.updated", "record.deleted",
        "field.changed", "stage.changed",
    }


def test_crm_core_actions_preserved():
    ids = get_action_ids("crm")
    for act in ["send_email", "create_record", "update_record",
                "create_task", "notify_user"]:
        assert act in ids, act


def test_crm_actions_are_exactly_the_agreed_set():
    """Send Slack is present here and gated per workspace at the API layer."""
    assert set(get_action_ids("crm")) == {
        "send_email", "send_slack", "create_task",
        "notify_user", "notify_team", "create_record", "update_record",
    }
