"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { agentsApi, AgentMessage, ChatStreamEvent, AgentConversationWithMessages } from "@/lib/api";

/**
 * Chat streaming state machine.
 *
 * Holds:
 *  - `pendingMessages`: optimistic user message + the in-flight
 *    assistant message that accumulates text_delta chunks as they
 *    arrive. Both vanish from this list once the server emits `done`
 *    and the canonical messages refetch via React Query.
 *  - `isStreaming`: true between send() and done/error/abort.
 *  - `currentCostUsd` / `currentTokens`: live token meter for the
 *    in-flight message.
 *
 * Exposes:
 *  - `send(content)`: fires the SSE request + populates the optimistic
 *    pair.
 *  - `stop()`: aborts the in-flight request, which causes the backend
 *    to persist whatever it accumulated and mark the execution as
 *    `cancelled`.
 *
 * Why pendingMessages instead of mutating the React Query cache:
 *   the canonical conversation list is the source of truth post-`done`.
 *   Keeping pending state in a separate hook avoids cache predicate
 *   races where a fast send could insert a duplicate when the server
 *   echo arrived faster than the optimistic insert.
 */
export function useAgentChatStream(
  workspaceId: string | null,
  agentId: string,
  conversationId: string,
) {
  const queryClient = useQueryClient();
  const [pendingMessages, setPendingMessages] = useState<AgentMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [currentCostUsd, setCurrentCostUsd] = useState<number | null>(null);
  const [currentTokens, setCurrentTokens] = useState<{ input?: number; output?: number } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Pending message ids — used in the cleanup effect so we can keep
  // the latest two ids around for a beat after `done` arrives (until
  // the canonical refetch returns) to avoid a UI flicker where the
  // streamed message momentarily vanishes.
  const pendingIdsRef = useRef<{ user: string; assistant: string } | null>(null);

  // Cleanup on unmount: kill any in-flight stream so we don't leak
  // a fetch after navigating away mid-response.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const send = useCallback(
    async (content: string) => {
      if (!workspaceId || !content.trim() || isStreaming) return;
      setError(null);
      setCurrentCostUsd(null);
      setCurrentTokens(null);

      const optimisticUserId = `optimistic-user-${Date.now()}`;
      const optimisticAssistantId = `optimistic-assistant-${Date.now()}`;
      pendingIdsRef.current = { user: optimisticUserId, assistant: optimisticAssistantId };

      const now = new Date().toISOString();
      const userOptimistic: AgentMessage = {
        id: optimisticUserId,
        conversation_id: conversationId,
        execution_id: null,
        role: "user",
        content,
        message_index: -1,
        created_at: now,
      };
      const assistantOptimistic: AgentMessage = {
        id: optimisticAssistantId,
        conversation_id: conversationId,
        execution_id: null,
        role: "assistant",
        content: "",
        message_index: -1,
        created_at: now,
      };
      setPendingMessages([userOptimistic, assistantOptimistic]);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const response = await agentsApi.streamMessage(
          workspaceId,
          agentId,
          conversationId,
          { content },
          controller.signal,
        );
        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let resolvedUserId: string | null = null;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          // SSE separator is "\n\n". Split, hold the trailing partial
          // for the next chunk. Each frame is a single `data: {...}`
          // line for our endpoints.
          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) >= 0) {
            const frame = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            if (!frame.startsWith("data:")) continue;
            const json = frame.slice(5).trim();
            if (!json) continue;
            let event: ChatStreamEvent;
            try {
              event = JSON.parse(json) as ChatStreamEvent;
            } catch {
              continue;
            }
            switch (event.type) {
              case "user_message":
                // Swap optimistic id for canonical.
                resolvedUserId = event.id;
                setPendingMessages((prev) =>
                  prev.map((m) =>
                    m.id === optimisticUserId
                      ? { ...m, id: event.id, created_at: event.created_at || m.created_at }
                      : m,
                  ),
                );
                break;
              case "text_delta":
                setPendingMessages((prev) =>
                  prev.map((m) =>
                    m.id === optimisticAssistantId
                      ? { ...m, content: m.content + event.text }
                      : m,
                  ),
                );
                break;
              case "tool_use_start": {
                const inputArgs = event.input;
                const toolCall = {
                  id: event.id,
                  name: event.tool,
                  args: inputArgs ?? {},
                };
                setPendingMessages((prev) =>
                  prev.map((m) =>
                    m.id === optimisticAssistantId
                      ? {
                          ...m,
                          tool_calls: [...(m.tool_calls ?? []), toolCall],
                        }
                      : m,
                  ),
                );
                break;
              }
              case "tool_result":
                // No-op for the optimistic message — the server will
                // persist this as its own tool-role message, and the
                // refetch on `done` will pull it in. Surface in the
                // existing assistant bubble's tool_calls if needed.
                break;
              case "usage":
                if (event.input_tokens != null || event.output_tokens != null) {
                  setCurrentTokens({
                    input: event.input_tokens ?? undefined,
                    output: event.output_tokens ?? undefined,
                  });
                }
                if (event.cost_usd != null) setCurrentCostUsd(event.cost_usd);
                setPendingMessages((prev) =>
                  prev.map((m) =>
                    m.id === optimisticAssistantId
                      ? {
                          ...m,
                          input_tokens: event.input_tokens ?? null,
                          output_tokens: event.output_tokens ?? null,
                          cost_usd: event.cost_usd ?? null,
                        }
                      : m,
                  ),
                );
                break;
              case "done":
                // Swap the optimistic assistant id and let the refetch
                // sweep up the canonical messages.
                setPendingMessages((prev) =>
                  prev.map((m) =>
                    m.id === optimisticAssistantId
                      ? { ...m, id: event.assistant_message_id, execution_id: event.execution_id }
                      : m,
                  ),
                );
                await queryClient.invalidateQueries({
                  queryKey: ["conversation", workspaceId, agentId, conversationId],
                });
                // Brief delay: keep pendingMessages around until the
                // canonical fetch resolves so we don't flicker.
                setTimeout(() => {
                  setPendingMessages([]);
                  pendingIdsRef.current = null;
                }, 80);
                setIsStreaming(false);
                return;
              case "error":
                setError(event.message);
                setPendingMessages((prev) =>
                  prev.map((m) =>
                    m.id === optimisticAssistantId
                      ? { ...m, content: m.content + `\n\n_Error: ${event.message}_` }
                      : m,
                  ),
                );
                break;
            }
          }
        }
        // Stream closed without a `done` (server hung up). Refetch to
        // sync with whatever the server persisted.
        await queryClient.invalidateQueries({
          queryKey: ["conversation", workspaceId, agentId, conversationId],
        });
        setPendingMessages([]);
        pendingIdsRef.current = null;
        setIsStreaming(false);
        if (!resolvedUserId) {
          setError((prev) => prev ?? "Stream ended unexpectedly");
        }
      } catch (err) {
        // AbortError is the user clicking Stop — not an error to
        // surface. Anything else is fatal.
        if ((err as { name?: string })?.name === "AbortError") {
          await queryClient.invalidateQueries({
            queryKey: ["conversation", workspaceId, agentId, conversationId],
          });
          setPendingMessages([]);
          pendingIdsRef.current = null;
          setIsStreaming(false);
          return;
        }
        setError(err instanceof Error ? err.message : "Stream failed");
        setIsStreaming(false);
      } finally {
        abortRef.current = null;
      }
    },
    [workspaceId, agentId, conversationId, isStreaming, queryClient],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  // Helper: merge pending optimistic messages onto the canonical list.
  // The chat surface uses this so its render is the union of "what the
  // server has confirmed" + "what we're streaming right now".
  const mergeMessages = useCallback(
    (canonical: AgentConversationWithMessages | undefined): AgentMessage[] => {
      const base = canonical?.messages ?? [];
      if (pendingMessages.length === 0) return base;
      // Dedupe by id so a refetch that already includes the just-
      // resolved message doesn't double up.
      const seen = new Set(base.map((m) => m.id));
      const extras = pendingMessages.filter((m) => !seen.has(m.id));
      return [...base, ...extras];
    },
    [pendingMessages],
  );

  return {
    pendingMessages,
    mergeMessages,
    isStreaming,
    currentCostUsd,
    currentTokens,
    error,
    send,
    stop,
  };
}
