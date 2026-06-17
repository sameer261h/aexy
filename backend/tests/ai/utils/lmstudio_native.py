"""Thin client for LM Studio's native `POST /api/v1/chat` endpoint.

Lives in tests/ (not src/) because the production code path goes through
the OpenAI-compatible `LMStudioProvider`. The native endpoint is only
useful for tests that need features the OpenAI-compat surface doesn't
expose:

  * `reasoning: "off"` — clean way to suppress chain-of-thought emission
    on Qwen / gpt-oss without the `/no_think` system-prompt hack.
  * `previous_response_id` — server-side stateful chats for multi-turn
    agent tests.
  * `integrations` (ephemeral_mcp + plugins) — exercise the MCP tool
    loop without LangGraph in the middle.
  * Structured `output[]` with typed items (`message` / `tool_call` /
    `reasoning` / `invalid_tool_call`) — easier to assert against than
    parsing OpenAI's `tool_calls` array.

Spec: https://lmstudio.ai/docs/developer/rest/chat
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import httpx


@dataclass
class NativeChatStats:
    input_tokens: int = 0
    total_output_tokens: int = 0
    reasoning_output_tokens: int = 0
    tokens_per_second: float = 0.0
    time_to_first_token_seconds: float = 0.0
    model_load_time_seconds: float | None = None


@dataclass
class NativeChatResponse:
    model_instance_id: str
    output: list[dict[str, Any]] = field(default_factory=list)
    stats: NativeChatStats = field(default_factory=NativeChatStats)
    response_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def messages(self) -> list[str]:
        """Return the text content of every `message`-type output item."""
        return [
            item.get("content", "")
            for item in self.output
            if item.get("type") == "message"
        ]

    def tool_calls(self) -> list[dict[str, Any]]:
        """Return all `tool_call` items in order."""
        return [item for item in self.output if item.get("type") == "tool_call"]

    def invalid_tool_calls(self) -> list[dict[str, Any]]:
        return [item for item in self.output if item.get("type") == "invalid_tool_call"]

    def reasoning_blocks(self) -> list[str]:
        return [
            item.get("content", "")
            for item in self.output
            if item.get("type") == "reasoning"
        ]


class LMStudioNativeClient:
    """Async client for LM Studio's `/api/v1/chat` endpoint.

    The OpenAI-compat path goes through `aexy.llm.lmstudio_provider`.
    This client exists only for tests.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:1234",
        api_token: str | None = None,
        timeout: float = 180.0,
    ):
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=30.0, pool=10.0),
        )

    async def chat(
        self,
        *,
        model: str,
        input: str | list[dict[str, Any]],
        system_prompt: str | None = None,
        reasoning: Literal["off", "low", "medium", "high", "on"] | None = "off",
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
        context_length: int | None = None,
        integrations: list[Any] | None = None,
        previous_response_id: str | None = None,
        store: bool = False,
        stream: bool = False,
    ) -> NativeChatResponse:
        """POST to `/api/v1/chat` and return a parsed response.

        `reasoning="off"` is the default because the test suite almost
        never wants chain-of-thought tokens — they're slow and eat the
        budget. Pass an explicit value to override.
        """
        if stream:
            raise NotImplementedError("Use chat_stream() for SSE responses")

        payload: dict[str, Any] = {
            "model": model,
            "input": input,
            "temperature": temperature,
            "store": store,
        }
        if system_prompt is not None:
            payload["system_prompt"] = system_prompt
        if reasoning is not None:
            payload["reasoning"] = reasoning
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if context_length is not None:
            payload["context_length"] = context_length
        if integrations:
            payload["integrations"] = integrations
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id

        response = await self._client.post("/api/v1/chat", json=payload)
        response.raise_for_status()
        data = response.json()

        stats_raw = data.get("stats", {}) or {}
        stats = NativeChatStats(
            input_tokens=stats_raw.get("input_tokens", 0),
            total_output_tokens=stats_raw.get("total_output_tokens", 0),
            reasoning_output_tokens=stats_raw.get("reasoning_output_tokens", 0),
            tokens_per_second=stats_raw.get("tokens_per_second", 0.0),
            time_to_first_token_seconds=stats_raw.get("time_to_first_token_seconds", 0.0),
            model_load_time_seconds=stats_raw.get("model_load_time_seconds"),
        )
        return NativeChatResponse(
            model_instance_id=data.get("model_instance_id", model),
            output=data.get("output", []) or [],
            stats=stats,
            response_id=data.get("response_id"),
            raw=data,
        )

    async def list_models(self) -> list[dict[str, Any]]:
        """GET /api/v1/models — returns `data` array verbatim."""
        response = await self._client.get("/api/v1/models")
        response.raise_for_status()
        return response.json().get("data", [])

    async def close(self) -> None:
        await self._client.aclose()
