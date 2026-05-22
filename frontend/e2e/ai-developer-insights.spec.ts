/**
 * E2E: /insights/me — the developer insights page calls a chain of
 * AI-derived endpoints (skill fingerprint, soft skills, growth
 * trajectory, predictions). This spec asserts the page renders
 * without a 401/5xx, even when the underlying data is sparse.
 *
 * A workspace with no git history will return empty insights — the
 * UI must render gracefully. The spec catches the regression class
 * where one of the chained endpoints starts returning 500 on empty.
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";
import { collectFatalApiErrors } from "./fixtures/ai-helpers";

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Developer insights (live)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
  });

  test("/insights/me loads without fatal API errors", async ({ page }) => {
    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    await page.goto("/insights/me", {
      waitUntil: "networkidle",
      timeout: 60_000,
    });

    // Match loosely on heading copy — the page may render different
    // labels depending on which widgets the developer's data
    // populates ("Your Insights" / "Developer Insights" / "Profile").
    await expect(
      page
        .getByRole("heading", { name: /insights|profile|growth/i })
        .first(),
    ).toBeVisible({ timeout: 30_000 });

    // No 401 (auth) and no 5xx (broken pipeline).
    expect(
      errors,
      `fatal API errors during /insights/me load: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
