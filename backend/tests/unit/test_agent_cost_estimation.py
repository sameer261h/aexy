"""Unit tests for `AgentService._estimate_cost_usd` (UX-CHAT-009).

The cost estimator is a pure function so we can hit it without DB or
LLM. The shipped rate card is static — when those numbers change,
these tests are the first thing that should break.
"""

from __future__ import annotations

import pytest

from aexy.services.agent_service import AgentService


class TestEstimateCostUsd:
    def test_anthropic_sonnet_matches_rate_card(self):
        # claude-3-5-sonnet @ ($3 / $15) per 1M tokens
        # 1000 in + 500 out = 1000*3 + 500*15 = 10_500 / 1M
        cost = AgentService._estimate_cost_usd(
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            input_tokens=1000,
            output_tokens=500,
        )
        assert cost == pytest.approx(0.0105, abs=1e-6)

    def test_anthropic_haiku_matches_rate_card(self):
        # claude-3-haiku @ ($0.25 / $1.25)
        # 10_000 in + 5_000 out = 10000*0.25 + 5000*1.25 = 8750 / 1M
        cost = AgentService._estimate_cost_usd(
            provider="anthropic",
            model="claude-3-haiku-20240307",
            input_tokens=10_000,
            output_tokens=5_000,
        )
        assert cost == pytest.approx(0.00875, abs=1e-6)

    def test_gemini_flash_matches_rate_card(self):
        # gemini-2.0-flash @ ($0.10 / $0.40)
        # 1000 in + 1000 out = 100 + 400 = 500 / 1M
        cost = AgentService._estimate_cost_usd(
            provider="gemini",
            model="gemini-2.0-flash",
            input_tokens=1000,
            output_tokens=1000,
        )
        assert cost == pytest.approx(0.0005, abs=1e-6)

    def test_openai_gpt4o_mini_matches_rate_card(self):
        # gpt-4o-mini @ ($0.15 / $0.60)
        # 1000 in + 1000 out = 150 + 600 = 750 / 1M
        cost = AgentService._estimate_cost_usd(
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=1000,
            output_tokens=1000,
        )
        assert cost == pytest.approx(0.00075, abs=1e-6)

    def test_prefix_match_resolves_versioned_model_ids(self):
        """The estimator matches by prefix so e.g.
        'claude-3-5-sonnet-20241022' resolves to the same rate as
        'claude-3-5-sonnet'. This guards against the rate card going
        stale when a vendor pushes a new pin."""
        without_suffix = AgentService._estimate_cost_usd(
            "anthropic", "claude-3-5-sonnet", 1000, 1000,
        )
        with_suffix = AgentService._estimate_cost_usd(
            "anthropic", "claude-3-5-sonnet-20251022", 1000, 1000,
        )
        assert without_suffix == with_suffix

    def test_gpt4o_does_not_shadow_gpt4o_mini(self):
        """Regression for the longest-prefix-wins sort: 'gpt-4o-mini'
        starts with 'gpt-4o', so without the explicit length sort the
        cheaper model would silently bill at the full-fat rate.
        gpt-4o = ($5 / $15), gpt-4o-mini = ($0.15 / $0.60).
        For 1k+1k tokens that's $0.020 vs $0.00075 — ~26x off."""
        full = AgentService._estimate_cost_usd("openai", "gpt-4o", 1000, 1000)
        mini = AgentService._estimate_cost_usd("openai", "gpt-4o-mini", 1000, 1000)
        # 1000 * 5 + 1000 * 15 = 20_000 / 1M
        assert full == pytest.approx(0.020, abs=1e-6)
        # 1000 * 0.15 + 1000 * 0.6 = 750 / 1M
        assert mini == pytest.approx(0.00075, abs=1e-6)
        # The whole point: they must not collapse to the same number.
        assert full != mini

    def test_gpt4o_dated_pin_matches_gpt4o_rate(self):
        """A dated OpenAI pin like 'gpt-4o-2024-08-06' is still gpt-4o,
        NOT gpt-4o-mini (which starts the same 6 chars). Verifies the
        prefix walk picks the right rate for vendor-pinned model ids."""
        dated = AgentService._estimate_cost_usd(
            "openai", "gpt-4o-2024-08-06", 1000, 1000,
        )
        base = AgentService._estimate_cost_usd("openai", "gpt-4o", 1000, 1000)
        assert dated == base

    def test_unknown_model_falls_back_to_midrange(self):
        """Unknown provider/model should still return a non-zero cost
        — the chat UI's token meter should never read $0 just because
        the operator switched to a new vendor that hasn't been added
        to the rate card yet."""
        cost = AgentService._estimate_cost_usd(
            provider="acme-llm",
            model="acme-large-v3",
            input_tokens=1000,
            output_tokens=1000,
        )
        # Fallback rate: $1 in / $3 out per 1M = 0.004 for 1k+1k
        assert cost > 0
        assert cost == pytest.approx(0.004, abs=1e-6)

    def test_zero_tokens_returns_zero(self):
        cost = AgentService._estimate_cost_usd("anthropic", "claude-3-5-sonnet", 0, 0)
        assert cost == 0

    def test_provider_is_case_insensitive(self):
        """The estimator lower-cases provider + model before matching."""
        cost_a = AgentService._estimate_cost_usd("anthropic", "claude-3-5-sonnet", 1000, 1000)
        cost_b = AgentService._estimate_cost_usd("ANTHROPIC", "Claude-3-5-Sonnet", 1000, 1000)
        assert cost_a == cost_b

    def test_returns_rounded_to_six_decimals(self):
        """USD storage uses NUMERIC(10,6); the estimator must not
        return values that overflow that precision."""
        cost = AgentService._estimate_cost_usd(
            "anthropic", "claude-3-5-sonnet", 1, 1
        )
        # Each token at the extremes contributes ~3e-9 + ~1.5e-8 dollars;
        # rounded to 6 decimals that's effectively 0.000000.
        # The point of this test is that the returned value, written
        # back to NUMERIC(10,6), round-trips without overflow.
        assert cost == round(cost, 6)


class TestSseFormat:
    """`_sse` is a one-liner but it's the wire format. Pin it."""

    def test_emits_sse_data_line(self):
        line = AgentService._sse({"type": "ping"})
        assert line == 'data: {"type": "ping"}\n\n'

    def test_handles_nested_payload(self):
        line = AgentService._sse({"type": "tool_use_start", "input": {"q": "hello"}})
        # Just enough to confirm json.dumps did its job + the framing
        # is correct. Don't pin the exact byte order of dict keys.
        assert line.startswith("data: ")
        assert line.endswith("\n\n")
        assert '"type": "tool_use_start"' in line
        assert '"q": "hello"' in line
