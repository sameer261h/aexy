/**
 * E2E: Trigger node — render + configure + edit + delete on the canvas.
 *
 * Smoke for the most-used node kind. Picks one representative subtype
 * (CRM `record.created`) for the structural checks; per-subtype
 * coverage lives in `ai-automation-triggers-*.spec.ts` (Layer B).
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

test.describe("AI / Automation node: trigger (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("adds a trigger, configures it, edits, then deletes", async ({ page }) => {
    const errors = collectFatalApiErrors(page);
    await openCanvas(page, { module: "crm" });

    // The blank canvas already ships with a default "trigger-1" (see
    // automationTemplates.ts::getDefaultNodes) — assertions need to
    // be relative to that initial count, not absolute.
    const initialTriggers = await canvasNodes(page, "trigger").count();

    // Add via palette (click-to-add affordance — bypasses ReactFlow
    // drop-zone hit-testing, which is flaky in Playwright).
    await addNodeFromPalette(page, "trigger", "record.created");
    await expect(canvasNodes(page, "trigger")).toHaveCount(initialTriggers + 1);

    // Adding a node auto-selects it → config panel opens.
    await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

    // The config panel should show the Object Type field for a CRM
    // record.created trigger.
    const objectType = getConfigField(page, /object type/i);
    await expect(objectType).toBeVisible({ timeout: 10_000 });

    // Close, then re-open the *newly added* trigger (last in the list)
    // via the helper so we exercise the click-to-select path explicitly.
    await closeNodeConfig(page);
    await expect(configPanel(page)).toBeHidden();
    await openNodeConfig(page, "trigger", initialTriggers /* index = last */);
    await expect(getConfigField(page, /object type/i)).toBeVisible();

    // Delete the newly-added trigger — RF default is Backspace on a
    // selected node. Leaves the default `trigger-1` behind.
    await closeNodeConfig(page);
    await canvasNodes(page, "trigger").nth(initialTriggers).click();
    await page.keyboard.press("Backspace");
    await expect(canvasNodes(page, "trigger")).toHaveCount(initialTriggers);

    expect(
      errors,
      `fatal API errors during trigger CRUD: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
