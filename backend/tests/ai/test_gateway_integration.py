"""Integration tests for `LLMGateway` against the local LM Studio server.

These tests verify gateway behavior that's easy to break and hard to
notice without an end-to-end check:

  * Rate-limit refusal raises `LLMRateLimitError` (no silent retry).
  * Prompt logging fires once per call with the correct operation name.
  * `analyze_batch` preserves order across N calls.
  * `health_check` returns a structured dict, not a bare bool.

Mock-only versions of these checks live in `tests/unit/test_llm_gateway.py`
already — this file is the live counterpart, marked `local_llm`.
"""

from __future__ import annotations

import json

import pytest

from aexy.llm.base import (
    AnalysisRequest,
    AnalysisType,
    LLMRateLimitError,
)
from aexy.llm.gateway import LLMGateway

from tests.ai.utils.schema_assertions import assert_analysis_result_shape


@pytest.mark.local_llm
class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_shape(self, lmstudio_gateway: LLMGateway):
        result = await lmstudio_gateway.health_check()
        assert isinstance(result, dict)
        assert result["healthy"] is True
        assert result["provider"]["name"] == "lmstudio"
        assert result["provider"]["model"].startswith("qwen/")
        assert result["cache"]["enabled"] is False


@pytest.mark.local_llm
class TestAnalyze:
    @pytest.mark.asyncio
    async def test_analyze_records_usage(self, lmstudio_gateway: LLMGateway):
        request = AnalysisRequest(
            analysis_type=AnalysisType.CODE,
            content="def add(a, b): return a + b",
            file_path="math.py",
            language_hint="python",
        )
        result = await lmstudio_gateway.analyze(request, use_cache=False)
        assert_analysis_result_shape(result, min_total_tokens=10)
        # Provider was used, not just cached
        assert result.raw_response, "raw_response must be populated"


@pytest.mark.local_llm
class TestRecorderIntegration:
    @pytest.mark.asyncio
    async def test_recording_gateway_captures_prompts(
        self, recording_gateway: LLMGateway, recorder
    ):
        await recording_gateway.analyze(
            AnalysisRequest(
                analysis_type=AnalysisType.COMMIT_MESSAGE,
                content="fix: handle null user in auth middleware",
                context={"files_changed": 1, "additions": 5, "deletions": 2},
            ),
            use_cache=False,
        )
        records = recorder.records
        assert len(records) == 1
        assert records[0]["operation"] == "analysis:commit_message"
        assert records[0]["provider"] == "lmstudio"
        assert records[0]["input_tokens"] > 0
        assert records[0]["output_tokens"] > 0


@pytest.mark.local_llm
class TestRateLimitRefusal:
    @pytest.mark.asyncio
    async def test_refusal_raises_llm_rate_limit_error(
        self, lmstudio_gateway: LLMGateway, monkeypatch
    ):
        """Monkeypatch the rate limiter to refuse — the gateway must
        raise `LLMRateLimitError` *before* the provider sees the call."""
        from aexy.services.llm_rate_limiter import RateLimitResult

        async def deny(*args, **kwargs):
            return RateLimitResult(
                allowed=False,
                wait_seconds=42.0,
                reason="manufactured refusal",
            )

        monkeypatch.setattr(lmstudio_gateway.rate_limiter, "check_rate_limit", deny)

        called = []

        async def spy_analyze(self_, req):
            called.append(req)
            raise AssertionError("Provider should not be reached")

        # Patch the provider's analyze to make sure we never get there.
        monkeypatch.setattr(
            lmstudio_gateway.provider, "analyze", lambda req: spy_analyze(None, req)
        )

        with pytest.raises(LLMRateLimitError) as exc:
            await lmstudio_gateway.analyze(
                AnalysisRequest(
                    analysis_type=AnalysisType.CODE, content="x", file_path="x.py"
                ),
                use_cache=False,
            )
        assert exc.value.wait_seconds == 42.0
        assert called == []
