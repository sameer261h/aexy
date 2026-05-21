"""Tests for `LMStudioProvider` — both mocked HTTP and live.

The mocked tests are the unit-test analogue of `test_deepseek_provider.py`
and run in CI without needing LM Studio. The live tests are gated by the
`local_llm` marker and exercise the real Qwen 3.5 model.
"""

from __future__ import annotations

import json

import httpx
import pytest

from aexy.llm.base import (
    AnalysisRequest,
    AnalysisType,
    LLMAPIError,
    LLMConfig,
    LLMRateLimitError,
)
from aexy.llm.lmstudio_provider import LMStudioProvider, QWEN_NO_THINK_SUFFIX

from tests.ai.utils.schema_assertions import (
    assert_analysis_result_shape,
    assert_task_signals_shape,
)


def _make_provider(
    *,
    model: str = "qwen/qwen3.5-9b",
    api_key: str = "",
    fallback: list[str] | None = None,
) -> LMStudioProvider:
    return LMStudioProvider(
        LLMConfig(
            provider="lmstudio",
            model=model,
            api_key=api_key,
            base_url=LMStudioProvider.DEFAULT_BASE_URL,
            max_tokens=2048,
            temperature=0.0,
            fallback_models=fallback or [],
        )
    )


def _patch_client(provider: LMStudioProvider, handler) -> None:
    """Replace the provider's AsyncClient with one backed by MockTransport."""
    provider._client = httpx.AsyncClient(
        base_url=provider._client.base_url,
        headers=dict(provider._client.headers),
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
    )


# ─── Constructor & identity ────────────────────────────────────────────


class TestConstructor:
    def test_no_api_key_is_ok(self):
        provider = _make_provider()
        assert provider.provider_name == "lmstudio"
        assert "Authorization" not in dict(provider._client.headers)

    def test_optional_api_key_added_to_headers(self):
        provider = _make_provider(api_key="proxy-token")
        assert provider._client.headers["Authorization"] == "Bearer proxy-token"

    def test_strips_primary_from_fallback(self):
        provider = _make_provider(
            model="qwen/qwen3.5-9b",
            fallback=["qwen/qwen3.5-9b", "openai/gpt-oss-20b"],
        )
        assert "qwen/qwen3.5-9b" not in provider._fallback_models
        assert provider._fallback_models == ["openai/gpt-oss-20b"]


# ─── System-prompt augmentation (Qwen reasoning suppression) ───────────


class TestSystemPromptAugmentation:
    def test_qwen_gets_no_think_suffix(self):
        p = _make_provider(model="qwen/qwen3.5-9b")
        out = p._augment_system_prompt("Answer briefly.")
        assert out.endswith(QWEN_NO_THINK_SUFFIX)

    def test_non_qwen_model_untouched(self):
        p = _make_provider(model="openai/gpt-oss-20b")
        assert p._augment_system_prompt("Answer.") == "Answer."

    def test_qwen_idempotent(self):
        p = _make_provider(model="qwen/qwen3.5-9b")
        already = "Be brief.\n\n/no_think"
        assert p._augment_system_prompt(already) == already


# ─── Mocked HTTP round-trip ────────────────────────────────────────────


class TestCallModel:
    @pytest.mark.asyncio
    async def test_request_shape_and_response_parsing(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 8, "completion_tokens": 2},
                },
            )

        p = _make_provider()
        _patch_client(p, handler)

        text, total, in_tok, out_tok = await p._call_model(
            "qwen/qwen3.5-9b", "sys", "user"
        )
        assert text == "hello"
        assert (in_tok, out_tok, total) == (8, 2, 10)
        assert captured["url"].endswith("/chat/completions")
        assert captured["body"]["model"] == "qwen/qwen3.5-9b"
        assert captured["body"]["stream"] is False
        # System prompt should have been augmented with /no_think for Qwen.
        assert captured["body"]["messages"][0]["content"].endswith(QWEN_NO_THINK_SUFFIX)
        assert captured["body"]["messages"][1] == {"role": "user", "content": "user"}

    @pytest.mark.asyncio
    async def test_empty_content_falls_back_to_reasoning(self):
        """When Qwen exhausts max_tokens on reasoning, we should still
        return *something* rather than an empty string — otherwise every
        JSON-parsing service downstream breaks silently."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "",
                                "reasoning_content": "I would say it's blue.",
                            },
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 50},
                },
            )

        p = _make_provider()
        _patch_client(p, handler)

        text, *_ = await p._call_model("qwen/qwen3.5-9b", "s", "u")
        assert text == "I would say it's blue."

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"retry-after": "5"}, text="too many")

        p = _make_provider()
        _patch_client(p, handler)

        with pytest.raises(LLMRateLimitError) as exc:
            await p._call_model("qwen/qwen3.5-9b", "s", "u")
        assert exc.value.wait_seconds == 5.0

    @pytest.mark.asyncio
    async def test_404_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="model not found")

        p = _make_provider()
        _patch_client(p, handler)

        with pytest.raises(LLMAPIError) as exc:
            await p._call_model("does/not-exist", "s", "u")
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_connect_error_message_mentions_lm_studio(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        p = _make_provider()
        _patch_client(p, handler)

        with pytest.raises(LLMAPIError) as exc:
            await p._call_model("qwen/qwen3.5-9b", "s", "u")
        assert "LM Studio" in str(exc.value) or "LMStudio" in str(exc.value)


class TestFallback:
    @pytest.mark.asyncio
    async def test_falls_back_on_primary_429(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            model = json.loads(request.content)["model"]
            calls.append(model)
            if model == "qwen/qwen3.5-9b":
                return httpx.Response(429, headers={"retry-after": "1"})
            return httpx.Response(
                200,
                json={
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                },
            )

        p = _make_provider(fallback=["openai/gpt-oss-20b"])
        _patch_client(p, handler)

        text, *_ = await p._call_api("s", "u")
        assert text == "ok"
        assert calls == ["qwen/qwen3.5-9b", "openai/gpt-oss-20b"]


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_ok_when_models_returns_200(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/models")
            return httpx.Response(200, json={"data": []})

        p = _make_provider()
        _patch_client(p, handler)
        assert await p.health_check() is True

    @pytest.mark.asyncio
    async def test_false_on_connect_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        p = _make_provider()
        _patch_client(p, handler)
        assert await p.health_check() is False


class TestGatewayWiring:
    def test_create_provider_returns_lmstudio(self):
        from aexy.llm.gateway import create_provider

        cfg = LLMConfig(
            provider="lmstudio", model="qwen/qwen3.5-9b", api_key=""
        )
        provider = create_provider(cfg)
        assert isinstance(provider, LMStudioProvider)
        assert provider.provider_name == "lmstudio"


# ─── Live tests against running LM Studio ──────────────────────────────


@pytest.mark.local_llm
class TestLiveLMStudio:
    """These call the real LM Studio server. Skipped automatically if it
    isn't reachable (see `pytest_collection_modifyitems` in conftest)."""

    @pytest.mark.asyncio
    async def test_health_check_passes(self, lmstudio_provider):
        assert await lmstudio_provider.health_check() is True

    @pytest.mark.asyncio
    async def test_call_api_returns_non_empty(self, lmstudio_provider):
        text, total, in_tok, out_tok = await lmstudio_provider._call_api(
            "You are a helpful assistant. Reply in fewer than 20 words.",
            "What is 2 + 2?",
        )
        assert text, "Expected non-empty response from LM Studio"
        assert in_tok > 0
        assert out_tok > 0
        assert total == in_tok + out_tok

    @pytest.mark.asyncio
    async def test_analyze_code_produces_valid_shape(self, lmstudio_provider):
        sample = (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n\n"
            "@app.get('/health')\n"
            "async def health():\n"
            "    return {'ok': True}\n"
        )
        result = await lmstudio_provider.analyze(
            AnalysisRequest(
                analysis_type=AnalysisType.CODE,
                content=sample,
                file_path="health.py",
                language_hint="python",
            )
        )
        assert_analysis_result_shape(result, min_total_tokens=10)
        assert result.provider == "lmstudio"
        assert result.model.startswith("qwen/")

    @pytest.mark.asyncio
    async def test_extract_task_signals_returns_valid_shape(self, lmstudio_provider):
        task = json.dumps(
            {
                "source": "github",
                "title": "Add Stripe billing",
                "description": "Integrate Stripe webhooks for subscriptions.",
                "labels": ["backend", "payments"],
            }
        )
        signals = await lmstudio_provider.extract_task_signals(task)
        assert_task_signals_shape(signals)
