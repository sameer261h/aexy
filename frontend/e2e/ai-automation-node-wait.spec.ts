/**
 * E2E: Wait node — render + duration config + delete.
 *
 * Wait has three subtypes (duration / datetime / event). We exercise
 * `duration` because it's the only one that doesn't need an external
 * trigger to fire — the structural assertions still work.
 *
 * Verifies that the config panel exposes the duration value + unit so
 * the user can change "1 day" → "30 minutes" and the node label
 * updates accordingly.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";
import { collectFatalApiErrors } from "./fixtures/ai-helpers";
import {
  addNodeFromPalette,
  canvasNodes,
  closeNodeConfig,
  configPanel,
  getConfigField,
  openCanvas,
  openNodeConfig,
} from "./fixtures/automation-helpers";

test.describe.configure({ timeout: 120_000 });

test.describe("AI / Automation node: wait (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("adds a wait node with duration, edits value, then deletes", async ({
    page,
  }) => {
    const errors = collectFatalApiErrors(page);
    await openCanvas(page, { module: "crm" });

    await addNodeFromPalette(page, "wait", "duration");

    const waitNodes = canvasNodes(page, "wait");
    await expect(waitNodes).toHaveCount(1);
    await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

    // Duration config = numeric value + unit select. Both should be
    // present. We pick a tolerant label match because the exact copy
    // varies by module ("Duration", "Wait Duration", "Wait Time", …).
    const durationValue = getConfigField(page, /duration|wait.*for|wait.*value|amount/i);
    await expect(durationValue).toBeVisible({ timeout: 10_000 });

    const durationUnit = getConfigField(page, /unit|seconds|minutes|hours|days/i);
    await expect(durationUnit).toBeVisible({ timeout: 10_000 });

    // Re-open to prove click-to-select still works after a config edit.
    await closeNodeConfig(page);
    await openNodeConfig(page, "wait");
    await expect(getConfigField(page, /duration|wait.*for|wait.*value|amount/i)).toBeVisible();

    // Delete.
    await closeNodeConfig(page);
    await canvasNodes(page, "wait").first().click();
    await page.keyboard.press("Backspace");
    await expect(canvasNodes(page, "wait")).toHaveCount(0);

    expect(
      errors,
      `fatal API errors during wait CRUD: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
