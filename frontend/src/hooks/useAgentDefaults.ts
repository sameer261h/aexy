"use client";

import { useQuery } from "@tanstack/react-query";
import { agentsApi } from "@/lib/api";

/**
 * Cached fetch for server-side agent defaults (UX-EDT-024).
 *
 * Replaces the hardcoded `gemini-2.0-flash` defaults scattered across
 * the wizard + edit page. The endpoint is cheap (synchronous read of
 * the LLMSettings struct) so we cache long — defaults change only
 * when operators redeploy with new env vars.
 *
 * Returns `data` and a `fallback` that callers can use during the
 * first-paint window so a missing/loading defaults call doesn't
 * leave the user staring at empty fields.
 */
export function useAgentDefaults(workspaceId: string | null) {
  const query = useQuery({
    queryKey: ["agentDefaults", workspaceId],
    queryFn: () => agentsApi.getAgentDefaults(workspaceId!),
    enabled: !!workspaceId,
    // Defaults rarely change; refetch once a day at most.
    staleTime: 24 * 60 * 60 * 1000,
    gcTime: 24 * 60 * 60 * 1000,
  });

  // Hardcoded fallback covers the loading window + offline use.
  // Matches what the prior implementation defaulted to so behavior
  // doesn't drift just because the API is slow.
  const fallback = {
    default_provider: "gemini" as const,
    default_model: "gemini-2.0-flash",
    provider_models: {
      claude: "claude-sonnet-4-20250514",
      gemini: "gemini-2.0-flash",
      openai: "gpt-4o-mini",
      ollama: "codellama:13b",
    },
    default_temperature: 0.7,
    default_max_tokens: 2000,
    default_confidence_threshold: 0.7,
    default_require_approval_below: 0.8,
    default_max_daily_responses: 100,
    default_response_delay_minutes: 5,
  };

  return {
    defaults: query.data ?? fallback,
    isLoading: query.isLoading,
    isReady: !!query.data,
  };
}
