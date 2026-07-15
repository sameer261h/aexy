"""Regression: writing-style email generation must go through the LLM gateway.

Bug: `WritingStyleService.generate_email` built a hardcoded
`AsyncAnthropic(api_key=settings.anthropic_api_key)` client, ignoring
LLM_PROVIDER entirely. On any non-Anthropic deployment (e.g. DeepSeek/Gemini
with no Anthropic key) the "generate email" agent action failed.

These tests confirm it now calls the gateway (which honours LLM_PROVIDER) and
raises cleanly when no provider is configured.
"""

import pytest

from aexy.services.writing_style_service import WritingStyleService


class _FakeGateway:
    def __init__(self):
        self.called_with = None

    async def call_llm(self, system_prompt, user_prompt, **kwargs):
        self.called_with = {"system_prompt": system_prompt, "user_prompt": user_prompt, **kwargs}
        return ("SUBJECT: Quick sync\nBODY: Hi Sam,\n\nLet's talk Tuesday.\n\nBest,", 42, 30, 12)


@pytest.mark.asyncio
async def test_generate_email_uses_gateway_not_hardcoded_anthropic(monkeypatch):
    fake = _FakeGateway()
    # generate_email does `from aexy.llm.gateway import get_llm_gateway` inside
    # the method, so patch it at the source module.
    monkeypatch.setattr("aexy.llm.gateway.get_llm_gateway", lambda: fake)

    svc = WritingStyleService(db=object())
    # Avoid any DB work — exercise the default-style path.
    async def _no_style(*a, **k):
        return None
    monkeypatch.setattr(svc, "get_style", _no_style)

    result = await svc.generate_email(
        developer_id="dev1",
        workspace_id="ws1",
        recipient_name="Sam",
        purpose="Schedule a sync",
    )

    assert fake.called_with is not None, "gateway.call_llm was not invoked"
    # Rate-limit / billing context is threaded through.
    assert fake.called_with["workspace_id"] == "ws1"
    assert fake.called_with["developer_id"] == "dev1"
    # The gateway response is parsed into subject/body.
    assert result["subject"] == "Quick sync"
    assert "Let's talk Tuesday." in result["body"]


@pytest.mark.asyncio
async def test_generate_email_raises_when_no_provider_configured(monkeypatch):
    monkeypatch.setattr("aexy.llm.gateway.get_llm_gateway", lambda: None)

    svc = WritingStyleService(db=object())
    async def _no_style(*a, **k):
        return None
    monkeypatch.setattr(svc, "get_style", _no_style)

    with pytest.raises(ValueError):
        await svc.generate_email(
            developer_id="dev1", workspace_id="ws1",
            recipient_name="Sam", purpose="x",
        )
