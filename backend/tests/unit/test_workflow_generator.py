"""Unit tests for `services.workflow_generator` (UX-DEF-004).

The generator wraps an LLM call but exposes two pure helpers that we
test in isolation here — `_strip_json_fence` for the parser-tolerance
case (some models still wrap output in ```json fences despite the
system prompt) and `_validate_workflow` for the shape contract that
keeps malformed LLM output away from the canvas.

The async `generate_workflow_from_prompt` is exercised against a stub
gateway so we cover the full happy / sad paths without burning real
LLM tokens.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from aexy.services import workflow_generator as wg


# ---------------------------------------------------------------------------
# _strip_json_fence — tolerant parsing
# ---------------------------------------------------------------------------


class TestStripJsonFence:
    def test_passes_clean_json_through_unchanged(self):
        clean = '{"nodes": [], "edges": []}'
        assert wg._strip_json_fence(clean) == clean

    def test_strips_backtick_fence_with_json_tag(self):
        wrapped = "```json\n{\"nodes\": []}\n```"
        out = wg._strip_json_fence(wrapped)
        assert out == '{"nodes": []}'

    def test_strips_backtick_fence_without_language_tag(self):
        wrapped = "```\n{\"nodes\": []}\n```"
        out = wg._strip_json_fence(wrapped)
        assert out == '{"nodes": []}'

    def test_strips_leading_and_trailing_whitespace(self):
        wrapped = "   \n```json\n{\"nodes\": []}\n```   \n"
        out = wg._strip_json_fence(wrapped)
        assert out == '{"nodes": []}'


# ---------------------------------------------------------------------------
# _validate_workflow — structural validation
# ---------------------------------------------------------------------------


def _ok_workflow() -> dict[str, Any]:
    """A minimal valid workflow used as the baseline for negative tests."""
    return {
        "nodes": [
            {"id": "trigger-1", "type": "trigger", "data": {"label": "When"}},
            {"id": "action-1", "type": "action", "data": {"label": "Then"}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger-1", "target": "action-1"},
        ],
    }


class TestValidateWorkflow:
    def test_accepts_minimum_valid_workflow(self):
        ok, err = wg._validate_workflow(_ok_workflow())
        assert ok is True
        assert err is None

    def test_rejects_non_object_payload(self):
        ok, err = wg._validate_workflow(["not", "an", "object"])  # type: ignore[arg-type]
        assert ok is False
        assert "JSON object" in (err or "")

    def test_rejects_missing_nodes(self):
        ok, err = wg._validate_workflow({"edges": []})
        assert ok is False
        assert "nodes" in (err or "")

    def test_rejects_empty_nodes(self):
        ok, err = wg._validate_workflow({"nodes": [], "edges": []})
        assert ok is False
        assert "nodes" in (err or "")

    def test_rejects_no_trigger(self):
        payload = _ok_workflow()
        # Flip the trigger to an action — no triggers left
        payload["nodes"][0]["type"] = "action"
        ok, err = wg._validate_workflow(payload)
        assert ok is False
        assert "trigger" in (err or "")

    def test_rejects_multiple_triggers(self):
        payload = _ok_workflow()
        payload["nodes"].append(
            {"id": "trigger-2", "type": "trigger", "data": {"label": "Also when"}}
        )
        ok, err = wg._validate_workflow(payload)
        assert ok is False
        assert "trigger" in (err or "")

    def test_rejects_duplicate_node_ids(self):
        payload = _ok_workflow()
        payload["nodes"].append(
            {"id": "trigger-1", "type": "action", "data": {}}
        )
        ok, err = wg._validate_workflow(payload)
        assert ok is False
        assert "duplicate" in (err or "")

    def test_rejects_unknown_node_type(self):
        payload = _ok_workflow()
        payload["nodes"][1]["type"] = "ferret"
        ok, err = wg._validate_workflow(payload)
        assert ok is False
        assert "unknown" in (err or "").lower()

    def test_rejects_edge_with_unknown_source(self):
        payload = _ok_workflow()
        payload["edges"].append(
            {"id": "e-bad", "source": "ghost", "target": "action-1"}
        )
        ok, err = wg._validate_workflow(payload)
        assert ok is False
        assert "source" in (err or "")

    def test_rejects_edge_with_unknown_target(self):
        payload = _ok_workflow()
        payload["edges"][0]["target"] = "ghost"
        ok, err = wg._validate_workflow(payload)
        assert ok is False
        assert "target" in (err or "")

    def test_accepts_all_valid_node_types(self):
        """The full set of recognized types from the system prompt should pass."""
        payload = {
            "nodes": [
                {"id": "t", "type": "trigger", "data": {}},
                {"id": "a", "type": "action", "data": {}},
                {"id": "c", "type": "condition", "data": {}},
                {"id": "w", "type": "wait", "data": {}},
                {"id": "ag", "type": "agent", "data": {}},
                {"id": "b", "type": "branch", "data": {}},
                {"id": "j", "type": "join", "data": {}},
            ],
            "edges": [
                {"source": "t", "target": "a"},
                {"source": "a", "target": "c"},
                {"source": "c", "target": "w"},
                {"source": "w", "target": "ag"},
                {"source": "ag", "target": "b"},
                {"source": "b", "target": "j"},
            ],
        }
        ok, err = wg._validate_workflow(payload)
        assert ok is True, err


# ---------------------------------------------------------------------------
# generate_workflow_from_prompt — happy + sad paths
# ---------------------------------------------------------------------------


class _StubGateway:
    """Minimal stand-in for `LLMGateway` that returns a canned response."""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.last_user_prompt: str | None = None

    async def call_llm(self, *, system_prompt, user_prompt, **kwargs):  # noqa: D401
        self.last_user_prompt = user_prompt
        # Match the gateway's documented return shape:
        # (response_text, total_tokens, input_tokens, output_tokens)
        return (self.response_text, 100, 60, 40)


@pytest.mark.asyncio
async def test_generate_returns_meta_and_payload(monkeypatch):
    payload = _ok_workflow()
    gateway = _StubGateway(json.dumps(payload))
    monkeypatch.setattr(wg, "get_llm_gateway", lambda: gateway)

    result = await wg.generate_workflow_from_prompt(
        prompt="when a deal closes, send slack",
        module="crm",
    )
    # _assign_positions injects `position` into each node, so compare
    # the LLM-shaped fields rather than full equality.
    assert [
        {k: v for k, v in n.items() if k != "position"} for n in result["nodes"]
    ] == payload["nodes"]
    assert all(isinstance(n.get("position"), dict) for n in result["nodes"])
    assert result["edges"] == payload["edges"]
    assert result["_meta"]["source"] == "llm_generated"
    assert result["_meta"]["module"] == "crm"
    # The user prompt should include the module hint so the LLM
    # biases toward module-specific nodes.
    assert "crm" in (gateway.last_user_prompt or "")


@pytest.mark.asyncio
async def test_generate_strips_json_fence(monkeypatch):
    """Some LLMs still wrap output in ```json fences. Generator should cope."""
    fenced = f"```json\n{json.dumps(_ok_workflow())}\n```"
    monkeypatch.setattr(wg, "get_llm_gateway", lambda: _StubGateway(fenced))
    result = await wg.generate_workflow_from_prompt(prompt="anything goes here")
    assert isinstance(result.get("nodes"), list)


@pytest.mark.asyncio
async def test_generate_raises_on_invalid_json(monkeypatch):
    monkeypatch.setattr(wg, "get_llm_gateway", lambda: _StubGateway("not even json"))
    with pytest.raises(ValueError, match="invalid JSON"):
        await wg.generate_workflow_from_prompt(prompt="anything goes here")


@pytest.mark.asyncio
async def test_generate_raises_on_invalid_shape(monkeypatch):
    """Valid JSON but violates the shape contract (no trigger)."""
    bad = {
        "nodes": [{"id": "a", "type": "action", "data": {}}],
        "edges": [],
    }
    monkeypatch.setattr(wg, "get_llm_gateway", lambda: _StubGateway(json.dumps(bad)))
    with pytest.raises(ValueError, match="invalid"):
        await wg.generate_workflow_from_prompt(prompt="anything goes here")


@pytest.mark.asyncio
async def test_generate_raises_when_gateway_disabled(monkeypatch):
    monkeypatch.setattr(wg, "get_llm_gateway", lambda: None)
    with pytest.raises(ValueError, match="gateway not configured"):
        await wg.generate_workflow_from_prompt(prompt="anything goes here")


# ---------------------------------------------------------------------------
# _assign_positions — ReactFlow needs `position: {x,y}` on every node
# ---------------------------------------------------------------------------


class TestAssignPositions:
    def _xy(self, payload: dict[str, Any], nid: str) -> tuple[int, int]:
        node = next(n for n in payload["nodes"] if n["id"] == nid)
        return node["position"]["x"], node["position"]["y"]

    def test_assigns_position_to_every_node(self):
        payload = {
            "nodes": [
                {"id": "t", "type": "trigger", "data": {}},
                {"id": "a", "type": "action", "data": {}},
            ],
            "edges": [{"source": "t", "target": "a"}],
        }
        wg._assign_positions(payload)
        for n in payload["nodes"]:
            assert isinstance(n["position"], dict)
            assert "x" in n["position"] and "y" in n["position"]

    def test_linear_chain_cascades_right(self):
        payload = {
            "nodes": [
                {"id": "n1", "type": "trigger", "data": {}},
                {"id": "n2", "type": "action", "data": {}},
                {"id": "n3", "type": "action", "data": {}},
            ],
            "edges": [
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3"},
            ],
        }
        wg._assign_positions(payload)
        x1, _ = self._xy(payload, "n1")
        x2, _ = self._xy(payload, "n2")
        x3, _ = self._xy(payload, "n3")
        assert x1 < x2 < x3

    def test_diamond_downstream_node_takes_longest_path(self):
        """Diamond regression: A→B→C→D plus A→D. D and its descendants
        must sit at the depth of the LONGER path, not the shorter one.
        The earlier BFS variant got this wrong when the short edge was
        discovered first."""
        payload = {
            "nodes": [
                {"id": "A", "type": "trigger", "data": {}},
                {"id": "B", "type": "action", "data": {}},
                {"id": "C", "type": "action", "data": {}},
                {"id": "D", "type": "action", "data": {}},
                {"id": "E", "type": "action", "data": {}},
            ],
            # Short edge A→D listed first so a naive BFS would settle D
            # at depth 1 before the longer A→B→C→D path arrives.
            "edges": [
                {"source": "A", "target": "D"},
                {"source": "A", "target": "B"},
                {"source": "B", "target": "C"},
                {"source": "C", "target": "D"},
                {"source": "D", "target": "E"},
            ],
        }
        wg._assign_positions(payload)
        xa, _ = self._xy(payload, "A")
        xb, _ = self._xy(payload, "B")
        xc, _ = self._xy(payload, "C")
        xd, _ = self._xy(payload, "D")
        xe, _ = self._xy(payload, "E")
        # Longest path: A(0) → B(1) → C(2) → D(3) → E(4)
        assert xa < xb < xc < xd < xe
        # And D must strictly be past C, not stuck at depth 1.
        assert xd > xc

    def test_preserves_existing_position(self):
        """If the LLM ever starts emitting positions, don't clobber them."""
        payload = {
            "nodes": [
                {"id": "t", "type": "trigger", "data": {},
                 "position": {"x": 999, "y": 999}},
                {"id": "a", "type": "action", "data": {}},
            ],
            "edges": [{"source": "t", "target": "a"}],
        }
        wg._assign_positions(payload)
        assert self._xy(payload, "t") == (999, 999)

    def test_cycle_does_not_crash(self):
        """A→B→A is a bug, but we still need to render rather than throw.
        Cycle nodes default to depth 0."""
        payload = {
            "nodes": [
                {"id": "A", "type": "trigger", "data": {}},
                {"id": "B", "type": "action", "data": {}},
            ],
            "edges": [
                {"source": "A", "target": "B"},
                {"source": "B", "target": "A"},
            ],
        }
        wg._assign_positions(payload)
        # Both should still have positions assigned.
        for n in payload["nodes"]:
            assert isinstance(n["position"], dict)
