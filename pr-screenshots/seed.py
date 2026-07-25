"""Create the demo data the screenshots need. Safe to run repeatedly."""
import os, json, urllib.request

TOK, WS = os.environ["TOK"], os.environ["WS"]
API = "http://localhost:8000/api/v1"
PERSON = "d64f7286-eaac-433f-b607-850a82514bb8"
DEAL = "5d25f0db-a505-4caa-b090-8eba9a760d8c"
STAGE_ATTR = "d1a96d37-1f62-40fb-be71-f45e8fbd1bcb"


def call(method, path, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        headers={"Authorization": "Bearer " + TOK, "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body else None)
    try:
        return json.load(urllib.request.urlopen(req))
    except Exception as exc:
        return {"err": str(exc)}


# A pipeline, so the deals board renders instead of offering to make one.
pipelines = call("GET", f"/workspaces/{WS}/crm/pipelines")
if not any(p.get("object_id") == DEAL for p in pipelines if isinstance(p, dict)):
    call("POST", f"/workspaces/{WS}/crm/pipelines", {
        "object_id": DEAL, "name": "Sales Pipeline",
        "is_default": True, "adopt_attribute_id": STAGE_ATTR})
    print("   created the deals pipeline")
else:
    print("   deals pipeline already present")

# Sequences with steps, including sub-day waits — the case PR 210 fixes.
PLAN = {
    "New Lead Welcome": ("Three touches over the first week after a lead arrives.", [
        ("email", {"subject": "Welcome to Aexy"}, 0, "minutes"),
        ("wait", {}, 2, "days"),
        ("email", {"subject": "Getting the most from your trial"}, 0, "minutes"),
        ("task", {"task_title": "Call the lead if no reply"}, 1, "days")]),
    "Trial Follow-up (same day)": ("Same-day follow-up using hour and minute waits.", [
        ("email", {"subject": "How is the trial going?"}, 0, "minutes"),
        ("wait", {}, 3, "hours"),
        ("task", {"task_title": "Check trial usage"}, 30, "minutes")]),
    "Dormant Re-engagement": ("Win back accounts that have gone quiet.", [
        ("email", {"subject": "We miss you"}, 0, "minutes"),
        ("wait", {}, 7, "days"),
        ("email", {"subject": "One last note"}, 0, "minutes")]),
}

existing = {s["name"]: s["id"] for s in call("GET", f"/workspaces/{WS}/crm/sequences")}
records = [r["id"] for r in call("GET", f"/workspaces/{WS}/crm/objects/{PERSON}/records?limit=8").get("records", [])]
cursor = 0

for name, (desc, steps) in PLAN.items():
    if name in existing:
        print(f"   sequence already present: {name}")
        cursor += 2
        continue
    seq = call("POST", f"/workspaces/{WS}/crm/sequences",
               {"name": name, "description": desc, "object_id": PERSON, "is_active": True})
    if "id" not in seq:
        print(f"   could not create {name}: {seq}")
        continue
    for position, (kind, config, value, unit) in enumerate(steps):
        call("POST", f"/workspaces/{WS}/crm/sequences/{seq['id']}/steps",
             {"step_type": kind, "config": config,
              "delay_value": value, "delay_unit": unit, "position": position})
    for _ in range(2):
        if cursor < len(records):
            call("POST", f"/workspaces/{WS}/crm/sequences/{seq['id']}/enroll",
                 {"record_id": records[cursor]})
            cursor += 1
    print(f"   created sequence: {name} ({len(steps)} steps)")
