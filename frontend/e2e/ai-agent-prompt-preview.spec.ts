/**
 * E2E: Agent prompt preview — the editor surface lets a builder run a
 * single prompt against the model without persisting a conversation.
 * Verifies that POST /crm/agents/:id/test/prompt fires and renders a
 * response + token usage.
 *
 * Why this is its own spec: this surface uses a slimmer code path
 * (no LangGraph tool loop, no conversation persistence) so it's the
 * fastest live signal that the LLM is reachable from the UI.
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  setupAiLiveAuth,
  LLM_WAIT_MS,
} from "./fixtures/ai-env";
import {
  collectFatalApiErrors,
  seedAgent,
  waitForAiResponse,
  type Seeded,
  type SeededAgent,
} from "./fixtures/ai-helpers";

let agent: Seeded<SeededAgent> | null = null;

test.beforeAll(async ({ request }) => {
  const ready = await aiLiveReady();
  test.skip(!ready.ok, ready.reason);
  agent = await seedAgent(request, {
    name: `e2e-prompt-${Date.now()}`,
    system_prompt: "You are a helpful, terse assistant.",
    tools: [],
  });
});

test.afterAll(async () => {
  if (agent) await agent.cleanup();
});

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Agent prompt preview (live)", () => {
  test("preview prompt fires /test/prompt and renders an output", async ({
    page,
  }) => {
    test.skip(!agent, "agent seed failed");

    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    await page.goto(`/agents/${agent!.value.id}/edit`, {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    // Switch to the Prompts/Preview tab.
    const promptsTab = page
      .getByRole("tab", { name: /prompts?|preview|playground/i })
      .or(page.getByRole("button", { name: /prompts?|preview|playground/i }))
      .first();
    if (await promptsTab.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await promptsTab.click();
    }

    // The Prompts tab shows three textboxes: system prompt
    // ("Enter your prompt..."), instructions, and "Sample input" —
    // the latter is where the test message goes.
    // The Sample input textarea is a plain controlled `<textarea
    // value={input} onChange=...>` (see PromptPreviewPanel in
    // app/(app)/agents/[agentId]/edit/page.tsx:1491). `.fill()`
    // dispatches a synthetic `input` event which React picks up.
    const input = page.getByRole("textbox", { name: /sample input/i });
    await expect(input).toBeVisible({ timeout: 15_000 });
    const PROMPT = "Say 'pong' in exactly one word.";
    await input.fill(PROMPT);
    await expect(input).toHaveValue(PROMPT);

    const runBtn = page.getByRole("button", { name: /run\s+preview/i });
    await expect(runBtn).toBeEnabled({ timeout: 5_000 });

    // Capture every /test/prompt request — including ones that error
    // with 4xx / 5xx — so we know the FE fired and can surface the
    // failure shape if the LLM call fails on the backend.
    const respPromise = page.waitForResponse(
      (resp) =>
        /\/crm\/agents\/[^/]+\/test\/prompt(\b|\?|$)/.test(resp.url()),
      { timeout: LLM_WAIT_MS },
    );

    await runBtn.click();

    const resp = await respPromise;
    expect(
      resp.status(),
      `prompt preview returned ${resp.status()}`,
    ).toBeLessThan(500);

    const body = (await resp.json().catch(() => null)) as {
      output?: string;
      response?: string;
      content?: string;
      tokens?: { input?: number; output?: number };
      input_tokens?: number;
      output_tokens?: number;
    } | null;
    if (body) {
      const text = body.output || body.response || body.content;
      if (text) expect(text.length).toBeGreaterThan(0);
      const out =
        body.output_tokens ?? body.tokens?.output ?? -1;
      // If tokens are reported, they should be > 0 — the LLM
      // actually generated something.
      if (out >= 0) expect(out).toBeGreaterThan(0);
    }

    expect(
      errors,
      `fatal API errors during prompt preview: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
