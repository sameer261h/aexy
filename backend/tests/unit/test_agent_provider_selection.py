"""Regression: LangGraph agents must build the right client per llm_provider.

Bug: BaseAgent.llm handled only `gemini` and `lmstudio`; every other provider
(openai, ollama, deepseek, openrouter, an unknown string) silently fell through
to `else -> ChatAnthropic`, so an agent configured for e.g. `deepseek` actually
ran on Claude (and failed when no Anthropic key was present).

These tests pin `BaseAgent._plan_llm`, the pure resolver the `llm` property
uses, so the family/model/base_url mapping is correct and an unknown provider
fails loudly instead of masquerading as Claude.
"""

import types

import pytest

from aexy.agents.base import BaseAgent

DEFAULT_MODEL = "claude-3-sonnet-20240229"  # BaseAgent.default_model


def _llm(**overrides):
    base = dict(
        gemini_api_key="gk",
        anthropic_api_key="ak",
        openai_api_key="ok",
        openai_model="gpt-4o-mini",
        deepseek_api_key="dk",
        openrouter_api_key="ork",
        openrouter_model="openai/gpt-4o",
        ollama_base_url="http://localhost:11434",
        ollama_model="codellama:13b",
        lmstudio_base_url="http://localhost:1234/v1",
        lmstudio_model="qwen/qwen3.5-9b",
        lmstudio_api_key="",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _plan(provider, model=DEFAULT_MODEL, **llm_over):
    return BaseAgent._plan_llm(provider, model, DEFAULT_MODEL, _llm(**llm_over))


def test_deepseek_uses_openai_family_and_deepseek_base():
    family, model, base_url, api_key = _plan("deepseek")
    assert family == "openai"
    assert base_url == "https://api.deepseek.com"
    assert api_key == "dk"
    assert model == "deepseek-chat"  # provider default when agent model is the class default


def test_openrouter_uses_openai_family_and_openrouter_base():
    family, model, base_url, api_key = _plan("openrouter")
    assert family == "openai"
    assert base_url == "https://openrouter.ai/api/v1"
    assert api_key == "ork"
    assert model == "openai/gpt-4o"


def test_openai_uses_openai_family_default_endpoint():
    family, model, base_url, api_key = _plan("openai")
    assert family == "openai"
    assert base_url is None  # default OpenAI endpoint
    assert (api_key, model) == ("ok", "gpt-4o-mini")


def test_ollama_uses_openai_compat_v1_endpoint():
    family, model, base_url, api_key = _plan("ollama")
    assert family == "openai"
    assert base_url == "http://localhost:11434/v1"
    assert api_key == "ollama"  # non-empty placeholder; Ollama ignores it
    assert model == "codellama:13b"


def test_lmstudio_unchanged():
    family, model, base_url, api_key = _plan("lmstudio")
    assert (family, base_url, api_key) == ("openai", "http://localhost:1234/v1", "lm-studio")


def test_gemini_and_claude_keep_their_own_families():
    assert _plan("gemini")[0] == "gemini"
    assert _plan("claude")[0] == "anthropic"
    assert _plan("anthropic")[0] == "anthropic"


def test_agent_model_override_wins_over_provider_default():
    # A non-default configured model should be used verbatim for deepseek.
    _family, model, _base, _key = _plan("deepseek", model="deepseek-reasoner")
    assert model == "deepseek-reasoner"


def test_unknown_provider_raises_instead_of_masquerading_as_claude():
    with pytest.raises(ValueError):
        _plan("totally-made-up")
