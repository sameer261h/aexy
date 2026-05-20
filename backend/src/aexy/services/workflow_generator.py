"""LLM-backed workflow generator (UX-DEF-004).

Given a one-line description ("when a deal closes, post to slack and
create a follow-up task"), return a ReactFlow-shaped {nodes, edges}
payload that the workflow canvas can drop in as a starting point.

The generated workflow is always validated client-side via the same
validation rules as user-built workflows — the LLM is a starting
point, not the source of truth. Worst case (LLM returns bad shape):
caller falls back to TemplateGallery.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from aexy.llm.gateway import get_llm_gateway

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a workflow designer for the Aexy automation
platform. The user describes what they want in plain English, and you
return a JSON object describing the workflow nodes + edges.

Output JSON shape:
{
  "nodes": [
    {
      "id": "string-id",
      "type": "trigger" | "action" | "condition" | "wait" | "agent" | "branch" | "join",
      "data": { ... type-specific data ... }
    }
  ],
  "edges": [
    {"id": "edge-id", "source": "node-id", "target": "node-id", "sourceHandle"?: "string"}
  ]
}

Node types + data shapes:

- trigger     {"label": "...", "trigger_type": "record.created" | "form.submitted" | "schedule.daily" | "webhook"}
- action      {"label": "...", "action_type": "send_email" | "create_record" | "update_record" | "send_slack" | "create_task" | "call_webhook"}
- condition   {"label": "...", "conditions": [{"field": "...", "operator": "eq", "value": "..."}], "conjunction": "and" | "or"}
- wait        {"label": "Wait N", "wait_type": "duration", "duration_value": 1, "duration_unit": "minutes" | "hours" | "days"}
- agent       {"label": "...", "agent_type": "support" | "sales" | "scheduling" | "onboarding"}
- branch      {"label": "Branch", "branches": [{"id": "branch-1", "label": "Path A"}, {"id": "branch-2", "label": "Path B"}]}
- join        {"label": "Join", "join_type": "all" | "any", "incoming_branches": 2}

Rules:
1. Every workflow MUST start with exactly one trigger node.
2. Every non-trigger node MUST have at least one incoming edge.
3. If you produce a `branch`, each `sourceHandle` on outgoing edges
   MUST match a `branches[].id` from the branch node's data.
4. If you produce a `condition`, outgoing edges use `sourceHandle`
   "true" and/or "false".
5. Keep ids short and human-readable (e.g. "trigger-1", "action-1",
   "condition-1"). Don't include timestamps.
6. Generate the minimum set of nodes that satisfies the request.
   Don't add aspirational "could also do" branches.

Reply with valid JSON only — no prose, no backticks, no commentary."""


def _strip_json_fence(raw: str) -> str:
    """Some models still wrap JSON in ```json fences despite the system
    prompt. Strip them. Leaves clean JSON untouched."""
    s = raw.strip()
    if s.startswith("```"):
        # Drop first fence line + trailing fence
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
        # Drop "json" language tag if present
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    return s.strip()


def _validate_workflow(payload: dict) -> tuple[bool, str | None]:
    """Quick structural validation. Returns (ok, error_message).

    Catches the most common LLM mistakes — missing trigger, dangling
    edges, malformed shape — before they reach the canvas. Doesn't
    enforce business rules (those live client-side); just shape.
    """
    if not isinstance(payload, dict):
        return False, "response was not a JSON object"
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list) or not nodes:
        return False, "nodes missing or empty"
    if not isinstance(edges, list):
        return False, "edges must be an array"

    ids: set[str] = set()
    triggers = 0
    for n in nodes:
        if not isinstance(n, dict):
            return False, "node must be an object"
        nid = n.get("id")
        ntype = n.get("type")
        if not isinstance(nid, str) or not nid:
            return False, "node missing id"
        if nid in ids:
            return False, f"duplicate node id {nid}"
        ids.add(nid)
        if ntype not in {"trigger", "action", "condition", "wait", "agent", "branch", "join"}:
            return False, f"unknown node type {ntype}"
        if ntype == "trigger":
            triggers += 1
    if triggers != 1:
        return False, "workflow must have exactly one trigger"

    for e in edges:
        if not isinstance(e, dict):
            return False, "edge must be an object"
        src = e.get("source")
        tgt = e.get("target")
        if src not in ids:
            return False, f"edge source {src!r} references unknown node"
        if tgt not in ids:
            return False, f"edge target {tgt!r} references unknown node"

    return True, None


async def generate_workflow_from_prompt(
    prompt: str,
    module: str | None = None,
    *,
    workspace_id: str | None = None,
    developer_id: str | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """Ask the LLM to draft a workflow from a plain-English prompt.

    Args:
        prompt: User description, e.g. "Notify slack when a deal closes".
        module: Optional module hint ("crm", "sprints"...) — biases the
            LLM toward module-specific triggers/actions.
        workspace_id: For rate-limit + billing scoping.
        developer_id: For rate-limit + billing scoping.
        db: For usage tracking.

    Returns:
        Dict with `nodes`, `edges`, plus a `_meta` block with the model
        name and any validation warning (in case the LLM's output was
        slightly off but salvageable). Empty `nodes`/`edges` on hard
        failure — caller falls back to TemplateGallery.

    Raises:
        ValueError: when the gateway isn't configured or the LLM
            response can't be coerced into a valid shape.
    """
    gateway = get_llm_gateway()
    if gateway is None:
        raise ValueError("LLM gateway not configured")

    user_prompt_parts = [f"Request: {prompt.strip()}"]
    if module:
        user_prompt_parts.append(f"Module hint: {module}")
    user_prompt_parts.append("Return JSON only.")
    user_prompt = "\n\n".join(user_prompt_parts)

    response, *_ = await gateway.call_llm(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tokens_estimate=1500,
        workspace_id=workspace_id,
        developer_id=developer_id,
        db=db,
    )

    stripped = _strip_json_fence(response)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as e:
        logger.warning("workflow_generator: invalid JSON: %s", e)
        raise ValueError("LLM returned invalid JSON") from e

    ok, err = _validate_workflow(payload)
    if not ok:
        logger.warning("workflow_generator: invalid shape: %s", err)
        raise ValueError(f"Generated workflow is invalid: {err}")

    payload.setdefault("_meta", {})
    payload["_meta"]["source"] = "llm_generated"
    if module:
        payload["_meta"]["module"] = module
    return payload
