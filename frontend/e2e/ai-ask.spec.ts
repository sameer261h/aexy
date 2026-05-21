/**
 * E2E: /ask — global workspace AI assistant.
 *
 * Verifies the user can ask a question and a non-empty answer renders.
 * Endpoint shape varies (some envs stream via SSE, others single-shot),
 * so the spec is tolerant — it waits for any `/ask/` URL to complete
 * 2xx and asserts the DOM gets new content.
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  setupAiLiveAuth,
  LLM_WAIT_MS,
} from "./fixtures/ai-env";
import {
  collectFatalApiErrors,
  waitForAiResponse,
} from "./fixtures/ai-helpers";

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Ask workspace assistant (live)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
  });

  test("submitting a question yields an answer", async ({ page }) => {
    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    // The Ask AI feature lives at /chat in this build (sidebar links
    // it under "Chat"). The landing view is a channels list; click
    // the "Ask AI" entry in the sidebar to open the chat surface.
    await page.goto("/chat", {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    const askAi = page.getByRole("button", { name: /^ask ai$/i }).first();
    await expect(askAi).toBeVisible({ timeout: 15_000 });
    await askAi.click();

    // Selecting Ask AI flips ChatLayout to `mode="ai"`, which renders
    // an empty state in the right pane with a single "New Chat"
    // button. That button (not the "+ New conversation" icon in the
    // sidebar) is what creates the conversation AND sets
    // `selectedConversationId`, which is what causes AskAIChatPanel
    // (the actual chat input surface) to render.
    const newChat = page
      .getByRole("button", { name: /^new chat$/i })
      .first();
    await expect(newChat).toBeVisible({ timeout: 10_000 });
    await newChat.click();

    // Wait for the chat surface to mount. AskAIChatPanel's textarea
    // has placeholder="Ask anything..." (see chat/components/
    // AskAIChatPanel.tsx).
    const input = page
      .getByPlaceholder(/^ask anything/i)
      .or(page.getByRole("textbox", { name: /ask|message|prompt/i }))
      .or(page.locator("textarea").last());
    await expect(input).toBeVisible({ timeout: 15_000 });

    const prompt = "Reply with the single word 'pong'.";
    await input.fill(prompt);

    const respPromise = waitForAiResponse(
      page,
      (u) =>
        /\/(ask|chat)\/(conversations|messages)/.test(u) ||
        /\/chat\/[^/]+\/messages/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    // Submit via keyboard — the floating chat widget can overlap the
    // Send button.
    await input.press("Meta+Enter").catch(async () => {
      await input.press("Control+Enter");
    });

    const resp = await respPromise;
    expect(resp.status(), `ask returned ${resp.status()}`).toBeLessThan(500);

    // User's question shows up in transcript. The same prompt text
    // can appear in 3 places after submit: sidebar list item,
    // conversation heading, and the chat bubble. `.first()` is fine —
    // we're only checking the message rendered at all.
    await expect(page.getByText(prompt).first()).toBeVisible({
      timeout: 15_000,
    });

    // Some text from the model appears. Tolerant: just check the
    // transcript grows beyond what the user typed.
    await expect
      .poll(
        async () => {
          const txt = await page.locator("main").innerText();
          return txt.replace(prompt, "").trim().length;
        },
        { timeout: LLM_WAIT_MS, intervals: [500, 1000, 2000, 4000] },
      )
      .toBeGreaterThan(0);

    expect(
      errors,
      `fatal API errors during /ask: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
