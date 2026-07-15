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
]
ORPHAN_ACTIONS = ["api_request", "enrich_record", "classify_record", "generate_summary"]


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


# --- core CRM capabilities preserved -------------------------------------

def test_crm_core_triggers_preserved():
    ids = get_trigger_ids("crm")
    for trig in ["record.created", "record.updated", "field.changed",
                 "status.changed", "stage.changed", "list_entry.added"]:
        assert trig in ids, trig


def test_crm_core_actions_preserved():
    ids = get_action_ids("crm")
    for act in ["send_email", "create_record", "update_record",
                "add_to_list", "run_agent", "webhook_call"]:
        assert act in ids, act
