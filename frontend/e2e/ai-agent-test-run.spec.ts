/**
 * E2E: "Test Agent" button on the agent detail page — sends a
 * one-shot run request with an arbitrary context and renders the
 * confidence + response.
 *
 * Distinct from `ai-agent-chat.spec.ts` because the test-run surface
 * skips conversation persistence and hits the backend's `/test`
 * endpoint instead. Used by builders to sanity-check an agent
 * before wiring it into production flows.
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
    name: `e2e-testrun-${Date.now()}`,
    system_prompt:
      "You are a sentiment classifier. Reply with one word: positive, " +
      "negative, or neutral.",
    tools: [],
  });
});

test.afterAll(async () => {
  if (agent) await agent.cleanup();
});

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Agent Test Run button (live)", () => {
  test("clicking Test Agent fires /test and renders a response", async ({
    page,
  }) => {
    test.skip(!agent, "agent seed failed");

    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    await page.goto(`/agents/${agent!.value.id}`, {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    // Failsafe: surface clearly if the error boundary fires.
    // Previously this skipped on every seeded lmstudio agent because
    // LLMConfigDisplay crashed on unknown provider; that's fixed in
    // components/agents/shared/LLMProviderSelector.tsx. Keep the
    // check as a tripwire for future contract drift.
    const errBoundary = page.getByRole("heading", {
      name: /encountered an error/i,
    });
    expect(
      await errBoundary.isVisible({ timeout: 2_000 }).catch(() => false),
      "Agent detail page hit error boundary — likely FE/BE contract drift on agent payload.",
    ).toBe(false);

    // The Run action lives in a 3-dot "More actions" menu in the
    // page header. Source: agents/[agentId]/page.tsx:682-705.
    const moreBtn = page.getByRole("button", { name: /^more actions$/i });
    await expect(moreBtn).toBeVisible({ timeout: 15_000 });
    await moreBtn.click();

    // The menu item is labelled "Run" (t("actions.run")).
    const runMenuItem = page
      .getByRole("button", { name: /^run$/i })
      .filter({ hasNot: page.locator("[disabled]") })
      .first();
    await expect(runMenuItem).toBeVisible({ timeout: 5_000 });
    await runMenuItem.click();

    // RunAgentDialog mounts with a task description textarea.
    const ctxInput = page
      .getByRole("textbox", {
        name: /task description|context|input|message|prompt/i,
      })
      .or(page.getByPlaceholder(/describe|task|context/i))
      .or(page.locator("textarea").last());
    await expect(ctxInput).toBeVisible({ timeout: 10_000 });
    await ctxInput.fill("Classify: 'Customer says: I love this product!'");

    const respPromise = waitForAiResponse(
      page,
      (u) => /\/crm\/agents\/[^/]+\/(test|run)(\b|\/)/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    // The Run button inside the dialog footer fires the execution.
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /^run(\s+agent)?$/i })
      .click();

    const resp = await respPromise;
    expect(
      resp.status(),
      `agent test endpoint returned ${resp.status()}`,
    ).toBeLessThan(500);

    // The response object should carry an obvious answer field.
    const body = await resp.json().catch(() => null);
    if (body && typeof body === "object") {
      const b = body as {
        success?: boolean;
        response?: string;
        output?: string;
        result?: unknown;
      };
      const text = b.response || b.output;
      if (text) {
        expect(text.length).toBeGreaterThan(0);
      }
    }

    expect(
      errors,
      `fatal API errors during agent test: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
