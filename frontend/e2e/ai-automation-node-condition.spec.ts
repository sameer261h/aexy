/**
 * E2E: Condition node — render + configure + delete.
 *
 * Condition is a "fixed" category with no subtypes — palette click adds
 * it directly. Distinct from a generic action because it exposes
 * `conditions[]` + `conjunction` ("and" / "or") in its config schema,
 * and the canvas renders two output handles (true / false) instead of
 * one.
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
  openCanvas,
  openNodeConfig,
} from "./fixtures/automation-helpers";

test.describe.configure({ timeout: 120_000 });

test.describe("AI / Automation node: condition (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("adds a condition, exposes true/false handles, configures, deletes", async ({
    page,
  }) => {
    const errors = collectFatalApiErrors(page);
    await openCanvas(page, { module: "crm" });

    // Condition has no subtypes — palette category click adds the node.
    await addNodeFromPalette(page, "condition");

    const conditionNodes = canvasNodes(page, "condition");
    await expect(conditionNodes).toHaveCount(1);
    await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

    // A condition needs two source handles (true + false) so it can
    // branch the workflow. ReactFlow gives each handle a
    // data-handleid; ConditionNode tags its sources `"true"` and
    // `"false"`. Both must render — without them the node can't
    // branch and the canvas is broken.
    const node = conditionNodes.first();
    await expect(
      node.locator('[data-handleid="true"]'),
      "condition node missing the `true` source handle",
    ).toBeVisible();
    await expect(
      node.locator('[data-handleid="false"]'),
      "condition node missing the `false` source handle",
    ).toBeVisible();

    // Close then re-open via click-to-select path.
    await closeNodeConfig(page);
    await expect(configPanel(page)).toBeHidden();
    await openNodeConfig(page, "condition");
    await expect(configPanel(page)).toBeVisible();

    // Close again so the panel backdrop doesn't intercept the canvas
    // click that triggers the delete.
    await closeNodeConfig(page);
    await canvasNodes(page, "condition").first().click();
    await page.keyboard.press("Backspace");
    await expect(canvasNodes(page, "condition")).toHaveCount(0);

    expect(
      errors,
      `fatal API errors during condition CRUD: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
