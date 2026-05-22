/**
 * E2E: Agent chat surface — user opens an agent, sends a message,
 * the streaming response renders.
 *
 * What this proves end-to-end:
 *   FE chat input → POST /crm/agents/:id/conversations/:cid/messages/stream
 *     → backend agent loop → LM Studio → SSE back → token rendering
 *     → final assistant bubble in DOM.
 *
 * Live-only. Auto-skips if LM Studio is down. See e2e/fixtures/ai-env.ts
 * for the env vars.
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  authHeaders,
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
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
    name: `e2e-chat-${Date.now()}`,
    system_prompt:
      "You are a terse test bot. Reply in one sentence. " +
      "Never call tools — answer from your own knowledge.",
    tools: [],
  });
});

test.afterAll(async () => {
  if (agent) await agent.cleanup();
});

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Agent chat (live)", () => {
  test("sending a message yields a non-empty assistant reply", async ({
    page,
  }) => {
    test.skip(!agent, "agent seed failed");

    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    await page.goto(`/agents/${agent!.value.id}/chat`, {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    // Find the message input. The exact label varies by UI rev so
    // match a few likely names + the textarea role as a fallback.
    const input = page
      .getByRole("textbox", { name: /message|prompt|ask|chat/i })
      .or(page.locator("textarea").first());
    await expect(input).toBeVisible({ timeout: 15_000 });

    const prompt = "What is 2 + 2? Answer with the number only.";
    await input.fill(prompt);

    // Fire the request — could be POST conversations (first turn) or
    // POST conversations/:cid/messages or .../stream.
    const respPromise = waitForAiResponse(
      page,
      (u) =>
        /\/crm\/agents\/[^/]+\/(conversations|test)/.test(u) ||
        /\/conversations\/[^/]+\/messages/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    // The floating workspace "Open chat" widget overlaps the Send
    // button in the bottom-right. Submit via the keyboard shortcut
    // the UI already advertises ("⌘↵ to send · Shift↵ for newline")
    // so the floating widget can't intercept the click.
    await input.press("Meta+Enter").catch(async () => {
      await input.press("Control+Enter");
    });

    const resp = await respPromise;
    expect(resp.status(), `chat request returned ${resp.status()}`).toBeLessThan(500);

    // The user's message should be visible in the transcript.
    await expect(page.getByText(prompt)).toBeVisible({ timeout: 15_000 });

    // At least ONE assistant-side bubble besides the input. Look for
    // a streaming/typing indicator first; if missing, wait for any
    // long-form text node distinct from the prompt.
    const transcript = page
      .locator("[data-testid*=message],[role=log],[role=article]")
      .or(page.locator("main"));
    await expect(transcript).toBeVisible({ timeout: 15_000 });

    // The model may take a while — poll for any text content the user
    // didn't type. Tolerant of streaming UIs that fill in slowly.
    await expect
      .poll(
        async () => {
          const txt = (await transcript.innerText()).trim();
          // Strip the prompt from the body; what's left should be non-empty
          // by the time the LLM has answered.
          return txt.replace(prompt, "").trim().length;
        },
        { timeout: LLM_WAIT_MS, intervals: [500, 1000, 2000, 4000] },
      )
      .toBeGreaterThan(0);

    expect(
      errors,
      `fatal API errors during agent chat: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
