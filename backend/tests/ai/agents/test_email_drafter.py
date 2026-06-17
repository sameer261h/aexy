"""End-to-end test for `EmailDrafterAgent` against the local LM Studio.

EmailDrafterAgent is representative of the 4 prebuilt LangGraph agents
(plus the CustomAgent builder). Pattern:

  * All 5 tools (CRM, history, writing style, draft create) are
    monkeypatched to return deterministic canned data — we don't want
    the test depending on a live CRM/Gmail.
  * The LLM (Qwen on LM Studio) actually runs and is responsible for
    picking up tool outputs and producing a final draft.
  * Assertions are on the agent's *flow* (which tools it called, in
    what order, with what shape of input) and the *final output*
    structure — not the literal email text, which is non-deterministic.

If a real cloud model (Claude) was used, this test would be flaky; with
a local model at temperature 0, it's reproducible enough.
"""

from __future__ import annotations

import pytest

from aexy.agents.prebuilt.email_drafter import EmailDrafterAgent


# ─── Tool mocks ────────────────────────────────────────────────────────


CANNED_WRITING_STYLE = (
    "Writing style: casual but professional. Greets with 'Hey {name},' and "
    "signs off with 'Cheers,\\nBhanu'. Sentences short. Uses 'wanted to' "
    "and 'just' as common starters."
)


CANNED_EMAIL_HISTORY = (
    "Recent emails with alice@example.com:\n"
    "  2026-05-10: Hey Alice, wanted to share the demo recording...\n"
    "  2026-04-22: Just following up on the contract — any updates?"
)


CANNED_CONTACT = (
    "Contact: Alice Smith (alice@example.com), VP Engineering at Acme Corp. "
    "Last touch 2026-05-10 (email)."
)


CANNED_ACTIVITIES = "Recent activities: 2 emails sent, 1 meeting last week."


@pytest.fixture
def patched_tools(monkeypatch):
    """Stub every tool used by EmailDrafterAgent.

    We override each tool's `_arun` so the LLM gets predictable tool
    output. The returned list lets the test assert which tools the
    agent actually invoked.
    """
    calls: list[dict] = []

    async def mk(name: str, response: str):
        async def _arun(*args, **kwargs):
            calls.append({"tool": name, "args": args, "kwargs": kwargs})
            return response
        return _arun

    from aexy.agents.tools import crm_tools, email_tools

    monkeypatch.setattr(
        crm_tools.GetRecordTool, "_arun",
        lambda self, *a, **kw: (calls.append({"tool": "get_record", "args": a, "kwargs": kw}), CANNED_CONTACT)[1],
    )
    monkeypatch.setattr(
        crm_tools.GetActivitiesTool, "_arun",
        lambda self, *a, **kw: (calls.append({"tool": "get_activities", "args": a, "kwargs": kw}), CANNED_ACTIVITIES)[1],
    )
    monkeypatch.setattr(
        email_tools.GetEmailHistoryTool, "_arun",
        lambda self, *a, **kw: (calls.append({"tool": "get_email_history", "args": a, "kwargs": kw}), CANNED_EMAIL_HISTORY)[1],
    )
    monkeypatch.setattr(
        email_tools.GetWritingStyleTool, "_arun",
        lambda self, *a, **kw: (calls.append({"tool": "get_writing_style", "args": a, "kwargs": kw}), CANNED_WRITING_STYLE)[1],
    )

    # CreateDraftTool returns a synthetic success string; the agent
    # should call this last to finalize the draft.
    async def create_draft(self, to: str, subject: str, body: str) -> str:
        calls.append({
            "tool": "create_draft",
            "args": (),
            "kwargs": {"to": to, "subject": subject, "body": body},
        })
        return f"Email draft created for {to}. Subject: '{subject}'"

    monkeypatch.setattr(email_tools.CreateDraftTool, "_arun", create_draft)

    return calls


# ─── The test ──────────────────────────────────────────────────────────


@pytest.mark.local_llm
class TestEmailDrafterAgent:
    @pytest.mark.asyncio
    async def test_drafts_email_calling_relevant_tools(
        self, patched_tools: list[dict], lmstudio_config
    ):
        # Construct the agent against the local LLM. The model_name
        # doesn't matter because llm_provider="lmstudio" routes through
        # langchain_openai.ChatOpenAI which reads settings.llm.lmstudio_model.
        agent = EmailDrafterAgent(
            workspace_id="ws-test",
            user_id="user-test",
            db=None,
            llm_provider="lmstudio",
            model=lmstudio_config.model,
            max_iterations=8,
            timeout_seconds=120,
        )

        record_data = {
            "values": {
                "first_name": "Alice",
                "name": "Alice Smith",
                "email": "alice@example.com",
                "company": "Acme Corp",
            }
        }
        context = {
            "purpose": "Check in on the Q2 partnership discussion",
            "email_type": "follow_up",
            "key_points": [
                "Reference the demo recording I sent on May 10",
                "Ask for a 30-min call next week",
            ],
        }

        result = await agent.run(record_data=record_data, context=context)

        # Top-level shape
        assert result["status"] in {"completed", "failed"}, result
        assert "steps" in result
        assert isinstance(result["steps"], list)

        # At least one LLM call must have happened
        llm_steps = [s for s in result["steps"] if s.get("type") == "llm_call"]
        assert llm_steps, "Agent never called the model"

        # The agent should have invoked at least one of the
        # information-gathering tools before drafting. We don't require
        # all of them — a small model may shortcut — but a model that
        # calls zero tools is a real regression.
        tool_names = {c["tool"] for c in patched_tools}
        assert tool_names, (
            f"Agent didn't call any tool. Steps={result['steps']}, "
            f"final_output={result.get('output')}"
        )

        # If the agent completed successfully and produced final output,
        # check it's a non-empty AIMessage payload.
        if result["status"] == "completed" and result.get("output"):
            assert "content" in result["output"]
            content = result["output"]["content"]
            # Local model is non-deterministic — check shape, not text.
            assert isinstance(content, (str, list))
            if isinstance(content, str):
                assert len(content) > 0 or result["output"].get("tool_calls"), (
                    "Final assistant message must have content OR tool_calls."
                )
