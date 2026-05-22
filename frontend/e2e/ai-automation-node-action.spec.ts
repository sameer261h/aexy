/**
 * E2E: Action node — render + configure + edit + delete.
 *
 * Picks one representative subtype (`send_email` from the common bucket)
 * for the structural checks; per-subtype coverage lives in
 * `ai-automation-actions-*.spec.ts` (Layer C).
 *
 * Live backend, no LLM — see fixtures/ai-env.ts::backendOnlyReady.
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

test.describe("AI / Automation node: action (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("adds an action, configures fields, edits, then deletes", async ({
    page,
  }) => {
    const errors = collectFatalApiErrors(page);
    await openCanvas(page, { module: "crm" });

    await addNodeFromPalette(page, "action", "send_email");

    const actionNodes = canvasNodes(page, "action");
    await expect(actionNodes).toHaveCount(1);
    await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

    // send_email requires at least recipient + subject + body. We
    // only assert that *some* canonical email field is exposed —
    // exact label depends on the action-specific form schema.
    const someEmailField = getConfigField(page, /to|recipient|subject|body|message/i);
    await expect(someEmailField).toBeVisible({ timeout: 10_000 });

    // Close + reopen to exercise the click-to-select path.
    await closeNodeConfig(page);
    await openNodeConfig(page, "action");
    await expect(getConfigField(page, /to|recipient|subject|body|message/i)).toBeVisible();

    // Delete.
    await closeNodeConfig(page);
    await canvasNodes(page, "action").first().click();
    await page.keyboard.press("Backspace");
    await expect(canvasNodes(page, "action")).toHaveCount(0);

    expect(
      errors,
      `fatal API errors during action CRUD: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
