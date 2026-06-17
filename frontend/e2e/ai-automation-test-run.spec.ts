/**
 * E2E: Workflow Test button against the LIVE backend.
 *
 * Live counterpart to `automations-workflow-test.spec.ts` (which is
 * fully mocked). The mocked one pins the Auto-save → Generate →
 * Run Test chain at the UI level; this one verifies the execute
 * endpoint actually accepts the FE payload, so a 422 / 500 surfaces
 * here instead of in prod.
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

test.describe("AI / Automation workflow Test (live)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
  });

  test("Test button on /new runs end-to-end without a 5xx", async ({
    page,
  }) => {
    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    await page.goto("/automations/new", {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    const startBlank = page
      .getByRole("button", {
        name: /start blank|blank canvas|start from scratch/i,
      })
      .first();
    if (await startBlank.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await startBlank.click();
    }

    const testButton = page.getByRole("button", { name: /^Test$/ });
    await expect(testButton).toBeVisible({ timeout: 15_000 });
    await testButton.click();

    // Modal opens, generate fills record id, then Run Test.
    await expect(
      page.getByRole("heading", { name: /test workflow/i }),
    ).toBeVisible({ timeout: 10_000 });

    const generateBtn = page.getByRole("button", { name: /^Generate$/ });
    if (await generateBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await generateBtn.click();
    }

    const respPromise = waitForAiResponse(
      page,
      (u) => /\/automations\/[^/]+\/workflow\/execute/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    await page
      .getByRole("dialog")
      .getByRole("button", { name: /run test/i })
      .click();

    const resp = await respPromise;
    expect(
      resp.status(),
      `workflow execute returned ${resp.status()}`,
    ).toBeLessThan(500);

    // The execute endpoint MUST NOT 422 — that means the FE payload
    // shape diverged from the Pydantic schema and is the bug class
    // this spec exists to catch.
    expect(
      resp.status(),
      `workflow execute returned 422 (schema mismatch)`,
    ).not.toBe(422);

    expect(
      errors,
      `fatal API errors during workflow Test: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
