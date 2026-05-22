/**
 * Helpers shared by every `ai-*.spec.ts` file.
 *
 * Three categories of helper:
 *
 *   1. SEEDING — create the data a test needs (agent, CRM record,
 *      compliance doc, …) via the backend API using the test JWT.
 *      Each returns a `{ id, cleanup }` pair; the spec calls cleanup
 *      in an `afterEach` (or just lets it leak — these are scratch
 *      workspaces).
 *
 *   2. NETWORK — wait helpers that match the *real* timing of an LLM
 *      call (5–120s), not Playwright's 5s default.
 *
 *   3. ASSERTION — `expectNoFatalApiErrors(page)` collects 401/5xx
 *      from the response stream and surfaces them at the end of the
 *      test, instead of letting them silently corrupt the UI.
 */

import type { APIRequestContext, Page, Response } from "@playwright/test";

import {
  API_BASE,
  LLM_WAIT_MS,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
} from "./ai-env";

// ─── Cleanup helper type ────────────────────────────────────────────

export interface Seeded<T> {
  value: T;
  cleanup: () => Promise<void>;
}

// ─── Seeding: CRM agent ─────────────────────────────────────────────

export interface SeededAgent {
  id: string;
  name: string;
}

/**
 * Create a throwaway agent in the workspace under test. Defaults to
 * lmstudio + qwen so the agent uses the local LLM when it runs. Spec
 * is free to override `body` to pin a specific tool list / model.
 */
export async function seedAgent(
  request: APIRequestContext,
  overrides: Partial<{
    name: string;
    description: string;
    agent_type: string;
    goal: string;
    system_prompt: string;
    tools: string[];
    llm_provider: "claude" | "gemini" | "lmstudio" | "openrouter" | "deepseek";
    model: string;
    temperature: number;
    max_tokens: number;
    max_iterations: number;
    timeout_seconds: number;
  }> = {},
): Promise<Seeded<SeededAgent>> {
  const name = overrides.name ?? `e2e-agent-${Date.now()}`;
  const body = {
    name,
    description: overrides.description ?? "E2E AI test agent",
    agent_type: overrides.agent_type ?? "custom",
    goal: overrides.goal ?? "Answer test questions concisely.",
    system_prompt:
      overrides.system_prompt ??
      "You are a test assistant. Keep answers under 100 words.",
    tools: overrides.tools ?? [],
    llm_provider: overrides.llm_provider ?? "lmstudio",
    model: overrides.model ?? "qwen/qwen3.5-9b",
    temperature: overrides.temperature ?? 0,
    max_tokens: overrides.max_tokens ?? 512,
    max_iterations: overrides.max_iterations ?? 4,
    timeout_seconds: overrides.timeout_seconds ?? 120,
  };

  const resp = await request.post(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/agents`,
    { headers: authHeaders(), data: body },
  );
  if (!resp.ok()) {
    throw new Error(
      `seedAgent failed: HTTP ${resp.status()} — ${await resp.text()}`,
    );
  }
  const data = (await resp.json()) as { id: string; name: string };

  return {
    value: { id: data.id, name: data.name },
    cleanup: async () => {
      try {
        await request.delete(
          `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/agents/${data.id}`,
          { headers: authHeaders() },
        );
      } catch {
        // ignore — these are throwaway resources
      }
    },
  };
}

// ─── Seeding: CRM record (for record-bound features) ───────────────

export interface SeededRecord {
  id: string;
  object_type: string;
}

/**
 * Create a CRM record (default object_type=contact). Used by the
 * email-draft and agent-test specs.
 *
 * Returns a `null` cleanup if the workspace has no CRM object schema
 * — some test workspaces are intentionally minimal; the spec should
 * then `test.skip(...)`.
 */
export async function seedCrmContact(
  request: APIRequestContext,
  overrides: Partial<{
    first_name: string;
    last_name: string;
    email: string;
    company: string;
  }> = {},
): Promise<Seeded<SeededRecord> | null> {
  const values = {
    first_name: overrides.first_name ?? "Alice",
    last_name: overrides.last_name ?? "Tester",
    name: `${overrides.first_name ?? "Alice"} ${overrides.last_name ?? "Tester"}`,
    email: overrides.email ?? `alice.${Date.now()}@example.com`,
    company: overrides.company ?? "Acme Corp",
  };
  const resp = await request.post(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/records`,
    {
      headers: authHeaders(),
      data: { object_type: "contact", values },
    },
  );
  if (resp.status() === 404) return null;
  if (!resp.ok()) {
    throw new Error(
      `seedCrmContact failed: HTTP ${resp.status()} — ${await resp.text()}`,
    );
  }
  const data = (await resp.json()) as { id: string; object_type: string };
  return {
    value: { id: data.id, object_type: data.object_type },
    cleanup: async () => {
      try {
        await request.delete(
          `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/records/${data.id}`,
          { headers: authHeaders() },
        );
      } catch {
        // ignore
      }
    },
  };
}

// ─── Seeding: compliance document ───────────────────────────────────

export interface SeededDocument {
  id: string;
  folder_id: string | null;
}

/**
 * Create a compliance document via the API. The file content itself
 * is not uploaded — the AI sidecar surface only needs the row + a
 * `Reannotate` to demonstrate the AI pipeline. Spec is free to upload
 * real bytes if it wants to validate end-to-end.
 */
export async function seedComplianceDoc(
  request: APIRequestContext,
  overrides: Partial<{
    name: string;
    description: string;
    folder_id: string | null;
  }> = {},
): Promise<Seeded<SeededDocument> | null> {
  // The compliance/documents endpoint requires file_key + file_size
  // (the row points at an existing object in RustFS). We don't
  // actually upload bytes here — we synthesize a key/size so the
  // row exists and the AI sidecar pipeline has something to point
  // at. Reannotate will mark ai_status without needing the bytes.
  const fakeKey = `wsfiles/e2e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}.pdf`;
  const resp = await request.post(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/compliance/documents`,
    {
      headers: authHeaders(),
      data: {
        name: overrides.name ?? `E2E AI Doc ${Date.now()}.pdf`,
        description: overrides.description ?? "Generated by ai-*.spec.ts",
        folder_id: overrides.folder_id ?? null,
        mime_type: "application/pdf",
        file_key: fakeKey,
        file_size: 1024,
      },
    },
  );
  if (resp.status() === 404) return null;
  if (!resp.ok()) {
    throw new Error(
      `seedComplianceDoc failed: HTTP ${resp.status()} — ${await resp.text()}`,
    );
  }
  const data = (await resp.json()) as { id: string; folder_id: string | null };
  return {
    value: { id: data.id, folder_id: data.folder_id ?? null },
    cleanup: async () => {
      try {
        await request.delete(
          `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/compliance/documents/${data.id}`,
          { headers: authHeaders() },
        );
      } catch {
        // ignore
      }
    },
  };
}

// ─── Network helpers ────────────────────────────────────────────────

/**
 * Wait for a single request matching `predicate` AND its response.
 * Distinct from `page.waitForResponse` because we want both sides:
 * the test asserts that the request actually fired (the LLM was
 * called) AND that the server returned non-error.
 *
 * Times out after `LLM_WAIT_MS` (default 180s) — the default
 * Playwright timeout is way too short for an LLM round-trip on a
 * local 9B model.
 */
export async function waitForAiResponse(
  page: Page,
  predicate: (url: string) => boolean,
  opts: { timeoutMs?: number } = {},
): Promise<Response> {
  return page.waitForResponse(
    (resp) => predicate(resp.url()) && resp.status() < 500,
    { timeout: opts.timeoutMs ?? LLM_WAIT_MS },
  );
}

/**
 * Wait for any of a set of LLM-bound endpoints (analyze, agents,
 * chat, ask, automation generate, …) to return. Most AI specs only
 * need to know "the model has responded" — the specific URL is
 * implementation detail.
 */
export const AI_ENDPOINT_PATTERNS = [
  /\/crm\/agents\/[^/]+\/conversations/,
  /\/crm\/agents\/[^/]+\/test/,
  /\/crm\/agents\/[^/]+\/run/,
  /\/crm\/writing-style\/(analyze|generate-email)/,
  /\/automations\/generate-workflow/,
  /\/automations\/[^/]+\/workflow\/execute/,
  /\/ask\/conversations\/[^/]+\/messages/,
  /\/analysis\/(code|commit|pr)/,
  /\/files\/[^/]+\/[^/]+\/(metadata|reannotate)/,
  /\/learning\/paths(\/|$)/,
  /\/assessments\/[^/]+\/candidates\/[^/]+\/reevaluate/,
  /\/reviews\/cycles\/(generate|generate-template)/,
  /\/predictions\//,
  /\/insights\/(ai|me|developers)/,
  /\/search\/files/,
];

export function isAiEndpoint(url: string): boolean {
  return AI_ENDPOINT_PATTERNS.some((p) => p.test(url));
}

// ─── Assertion helper ───────────────────────────────────────────────

/**
 * Hook into page responses and collect every 401/5xx (and 4xx if
 * `strict: true`) so the test can fail loudly at the end with a list
 * of what broke. Without this, a failing /me call masquerades as a
 * generic "page didn't render" error.
 *
 *   const errors = collectFatalApiErrors(page);
 *   ...
 *   expect(errors, JSON.stringify(errors)).toEqual([]);
 */
export function collectFatalApiErrors(
  page: Page,
  opts: { strict?: boolean } = {},
): { url: string; status: number }[] {
  const failures: { url: string; status: number }[] = [];
  const strict = opts.strict ?? false;
  page.on("response", (resp) => {
    const status = resp.status();
    if (!resp.url().includes(API_BASE)) return;
    if (status === 401 || status >= 500) {
      failures.push({ url: resp.url(), status });
    } else if (strict && status >= 400) {
      failures.push({ url: resp.url(), status });
    }
  });
  return failures;
}

/**
 * Best-effort shim: tries to find a "Test" or "Run" or "Generate"
 * button by role, scoped to a region if given. Returns the first
 * match. Used by specs where the exact button label depends on the
 * UI revision (and we don't want to break every time copy moves).
 */
export async function clickFirstByName(
  page: Page,
  names: (string | RegExp)[],
  opts: { timeout?: number } = {},
): Promise<void> {
  const t = opts.timeout ?? 10_000;
  for (const name of names) {
    const btn = page.getByRole("button", { name }).first();
    if (await btn.isVisible({ timeout: 500 }).catch(() => false)) {
      await btn.click({ timeout: t });
      return;
    }
  }
  throw new Error(
    `clickFirstByName: none of ${JSON.stringify(names.map(String))} visible`,
  );
}
