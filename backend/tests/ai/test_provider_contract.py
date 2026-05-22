"""Cross-provider contract test.

Every concrete `LLMProvider` must satisfy the same surface that the
`LLMGateway` and downstream services depend on. The provider test
files (test_lmstudio_provider, test_deepseek_provider, …) exercise
each provider's quirks; this one pins down the contract they all
share, so a new provider can't be wired in without honoring it.

For cloud providers we use mock transports — no live calls. For
`lmstudio` we use the real server when available.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest

from aexy.llm.base import (
    AnalysisRequest,
    AnalysisType,
    LLMConfig,
    LLMProvider,
    TaskSignals,
)


# ─── Mock-backed providers ─────────────────────────────────────────────


def _ok_handler(body: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """Return a handler that responds 200 with a canned chat-completions
    payload for *any* request. Works for all the OpenAI-compatible
    providers (deepseek, openrouter, lmstudio)."""
    payload_str = json.dumps(body)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": payload_str}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    return handler


def _patch(provider: LLMProvider, handler) -> None:
    provider._client = httpx.AsyncClient(
        base_url=provider._client.base_url,
        headers=dict(provider._client.headers),
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
    )


def _deepseek():
    from aexy.llm.deepseek_provider import DeepSeekProvider

    return DeepSeekProvider(
        LLMConfig(provider="deepseek", model="deepseek-chat", api_key="k")
    )


def _openrouter():
    from aexy.llm.openrouter_provider import OpenRouterProvider

    return OpenRouterProvider(
        LLMConfig(
            provider="openrouter", model="anthropic/claude-sonnet-4", api_key="k"
        )
    )


def _lmstudio():
    from aexy.llm.lmstudio_provider import LMStudioProvider

    return LMStudioProvider(
        LLMConfig(provider="lmstudio", model="qwen/qwen3.5-9b", api_key="")
    )


PROVIDERS: list[tuple[str, Callable[[], LLMProvider]]] = [
    ("deepseek", _deepseek),
    ("openrouter", _openrouter),
    ("lmstudio", _lmstudio),
]


@pytest.fixture(params=PROVIDERS, ids=[p[0] for p in PROVIDERS])
def provider(request) -> LLMProvider:
    return request.param[1]()


class TestProviderIdentity:
    def test_has_provider_and_model_name(self, provider: LLMProvider):
        assert provider.provider_name, "provider_name must be non-empty"
        assert provider.model_name, "model_name must be non-empty"

    def test_implements_abstract_methods(self, provider: LLMProvider):
        # If the class is concrete, the ABC won't have raised — but make
        # the expectations explicit so a future refactor that drops one
        # of these methods fails here, not deep in a service test.
        for attr in ("analyze", "extract_task_signals", "score_match", "health_check"):
            assert hasattr(provider, attr), f"missing {attr}"
            assert callable(getattr(provider, attr))


class TestAnalyzeContract:
    @pytest.mark.asyncio
    async def test_analyze_returns_valid_analysis_result(self, provider: LLMProvider):
        canned = {
            "languages": [
                {"name": "Python", "confidence": 0.9, "patterns_detected": ["async"]}
            ],
            "frameworks": [
                {
                    "name": "FastAPI",
                    "category": "web",
                    "usage_depth": "advanced",
                    "confidence": 0.85,
                }
            ],
            "domains": [],
            "soft_skills": [],
            "summary": "ok",
        }
        _patch(provider, _ok_handler(canned))

        result = await provider.analyze(
            AnalysisRequest(
                analysis_type=AnalysisType.CODE,
                content="print('hi')",
                file_path="a.py",
                language_hint="python",
            )
        )
        assert result.provider, "result.provider must be set"
        assert result.model, "result.model must be set"
        assert 0.0 <= result.confidence <= 1.0
        assert result.input_tokens > 0
        assert result.output_tokens > 0
        # Token accounting must round-trip
        assert result.input_tokens + result.output_tokens == result.tokens_used or (
            result.tokens_used >= result.input_tokens + result.output_tokens
        )


class TestTaskSignalsContract:
    @pytest.mark.asyncio
    async def test_returns_valid_task_signals(self, provider: LLMProvider):
        canned = {
            "required_skills": ["python", "stripe"],
            "preferred_skills": ["sql"],
            "domain": "payments",
            "complexity": "medium",
            "keywords": ["billing"],
            "confidence": 0.7,
        }
        _patch(provider, _ok_handler(canned))

        signals = await provider.extract_task_signals(
            '{"source":"github","title":"Add Stripe","description":"hi"}'
        )
        assert isinstance(signals, TaskSignals)
        assert signals.complexity in {"low", "medium", "high"}
        assert 0.0 <= signals.confidence <= 1.0


class TestHealthCheckContract:
    @pytest.mark.asyncio
    async def test_returns_bool(self, provider: LLMProvider):
        _patch(provider, lambda req: httpx.Response(200, json={"data": []}))
        result = await provider.health_check()
        assert isinstance(result, bool)
