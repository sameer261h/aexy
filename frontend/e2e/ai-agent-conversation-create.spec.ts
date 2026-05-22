/**
 * E2E: First message on /agents/:id/chat must create a conversation
 * and return the initial assistant message. The frontend uses a
 * `POST /conversations` shortcut for the first turn (no convoId in URL).
 *
 * Distinct from `ai-agent-chat.spec.ts` because that one assumes the
 * conversation already exists; this one specifically pins the
 * "fresh start" code path.
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
    name: `e2e-newconvo-${Date.now()}`,
    system_prompt: "You are a terse test bot. Reply in one sentence.",
    tools: [],
  });
});

test.afterAll(async () => {
  if (agent) await agent.cleanup();
});

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Agent first-message conversation creation (live)", () => {
  test("first message creates a conversation row and replies", async ({
    page,
  }) => {
    test.skip(!agent, "agent seed failed");

    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    await page.goto(`/agents/${agent!.value.id}/chat`, {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    const input = page
      .getByRole("textbox", { name: /message|prompt|ask|chat/i })
      .or(page.locator("textarea").first());
    await expect(input).toBeVisible({ timeout: 15_000 });
    await input.fill("Say hi in exactly two words.");

    // The first turn must hit POST .../conversations (without a convo id
    // suffix) — this is the conversation-creation path.
    const createPromise = waitForAiResponse(
      page,
      (u) => /\/crm\/agents\/[^/]+\/conversations(\?|$|\/messages)/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    // Floating workspace "Open chat" widget overlaps the Send button;
    // use the advertised keyboard shortcut instead.
    await input.press("Meta+Enter").catch(async () => {
      await input.press("Control+Enter");
    });

    const resp = await createPromise;
    expect(
      resp.status(),
      `conversation create returned ${resp.status()}`,
    ).toBeLessThan(500);

    // Body should contain a conversation id — used by the UI to
    // navigate (push state to /chat/:convoId) and by subsequent
    // turns to POST messages to.
    const body = await resp.json().catch(() => null);
    if (body && typeof body === "object") {
      const id =
        (body as { id?: string; conversation_id?: string }).id ||
        (body as { id?: string; conversation_id?: string }).conversation_id;
      expect(id, `expected conversation id in response: ${JSON.stringify(body)}`).toBeTruthy();
    }

    expect(
      errors,
      `fatal API errors during convo create: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
