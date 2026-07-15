"""Regression: the Ask (floating-widget) AI chat must honor LLM_PROVIDER.

Bug: AskService ignored `settings.llm.llm_provider` and auto-picked the first
available API key in the order Anthropic > OpenAI > Gemini. A deployment
configured for `deepseek` therefore still called Gemini — and when the Gemini
key was suspended (403), AI chat silently failed to stream any response.

These tests pin the resolver so a configured provider is always used (and
DeepSeek/OpenRouter/LM Studio route through the OpenAI-compatible path with the
correct base URL), with auto-detect only as a last-resort fallback.
"""

import types

import pytest

from aexy.services.ask_service import (
    DEEPSEEK_API_URL,
    OPENAI_API_URL,
    OPENROUTER_API_URL,
    AskService,
)


def _llm(**overrides):
    base = dict(
        llm_provider="",
        llm_model="",
        openai_api_key="",
        openai_model="",
        gemini_api_key="",
        gemini_model="",
        deepseek_api_key="",
        openrouter_api_key="",
        openrouter_model="",
        lmstudio_base_url="http://localhost:1234/v1",
        lmstudio_model="qwen/qwen3.5-9b",
        lmstudio_api_key="",
        anthropic_api_key="",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def test_deepseek_is_honored_over_available_gemini_key():
    # The exact prod scenario: provider=deepseek, but a Gemini key is also set.
    # Old behavior picked Gemini; the resolver must pick DeepSeek.
    llm = _llm(llm_provider="deepseek", llm_model="deepseek-chat",
               deepseek_api_key="dk", gemini_api_key="gk")
    family, api_key, model, url = AskService._resolve_provider("deepseek", llm, "")
    assert family == "openai"          # OpenAI-compatible streaming path
    assert api_key == "dk"
    assert model == "deepseek-chat"
    assert url == DEEPSEEK_API_URL


def test_configured_provider_without_key_falls_back_to_autodetect():
    # provider=deepseek but no DeepSeek key -> resolver declines, so __init__
    # falls back to auto-detect (which would pick the Gemini key here).
    llm = _llm(llm_provider="deepseek", gemini_api_key="gk")
    assert AskService._resolve_provider("deepseek", llm, "") is None
    assert AskService._auto_detect(llm, "")[0] == "gemini"


def test_claude_provider_uses_anthropic_path():
    llm = _llm(llm_provider="claude", llm_model="claude-sonnet-4-20250514")
    family, api_key, model, url = AskService._resolve_provider("claude", llm, "ak")
    assert (family, api_key, model, url) == ("anthropic", "ak", "claude-sonnet-4-20250514", None)


def test_openrouter_routes_through_openai_path():
    llm = _llm(llm_provider="openrouter", openrouter_api_key="ok", openrouter_model="openai/gpt-4o")
    family, api_key, model, url = AskService._resolve_provider("openrouter", llm, "")
    assert family == "openai"
    assert url == OPENROUTER_API_URL


def test_lmstudio_uses_local_base_url_no_key_required():
    llm = _llm(llm_provider="lmstudio")
    family, api_key, model, url = AskService._resolve_provider("lmstudio", llm, "")
    assert family == "openai"
    assert api_key  # non-empty placeholder so the Authorization header is valid
    assert url == "http://localhost:1234/v1/chat/completions"


def test_openai_provider_uses_openai_url():
    llm = _llm(llm_provider="openai", openai_api_key="ok")
    _family, _key, _model, url = AskService._resolve_provider("openai", llm, "")
    assert url == OPENAI_API_URL


@pytest.mark.parametrize("provider", ["deepseek", "openai", "gemini", "openrouter"])
def test_unconfigured_provider_declines(provider):
    # No keys set anywhere -> resolver declines for every keyed provider.
    assert AskService._resolve_provider(provider, _llm(llm_provider=provider), "") is None


def test_autodetect_none_when_nothing_configured():
    assert AskService._auto_detect(_llm(), "")[0] == "none"
