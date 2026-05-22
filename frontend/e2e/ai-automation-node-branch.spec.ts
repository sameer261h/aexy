/**
 * E2E: Branch node — render + multiple output handles + delete.
 *
 * Branch has no subtypes — palette category click adds it directly with
 * a default of 2 branches. Each branch is a named output handle, so the
 * node must render at least 2 source handles for the user to wire
 * downstream actions to.
 *
 * Edge-drawing in ReactFlow via Playwright mouse events is flaky and
 * lives in Layer E's canvas-wire spec; this one only asserts the
 * branch *exposes* its handles + config panel.
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
} from "./fixtures/automation-helpers";

test.describe.configure({ timeout: 120_000 });

test.describe("AI / Automation node: branch (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("adds a branch with ≥2 output handles, configures, then deletes", async ({
    page,
  }) => {
    const errors = collectFatalApiErrors(page);
    await openCanvas(page, { module: "crm" });

    // Branch has no subtypes — direct add on the category click.
    await addNodeFromPalette(page, "branch");

    const branchNodes = canvasNodes(page, "branch");
    await expect(branchNodes).toHaveCount(1);
    await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

    // Branch default ships with 2 branches (see WorkflowCanvas.tsx:563
    // — `branches: [{id:"branch-1",label:"Branch 1"},{id:"branch-2",label:"Branch 2"}]`).
    // ReactFlow tags each handle with the CSS class `source` or `target`
    // (NOT a data-handletype attribute). Count source handles to verify
    // the node can actually branch the workflow.
    const node = branchNodes.first();
    const sourceHandles = node.locator(".react-flow__handle.source");
    expect(
      await sourceHandles.count(),
      "branch node must expose ≥2 source handles to be useful",
    ).toBeGreaterThanOrEqual(2);

    // Config panel for a branch should expose the branches list so
    // the user can rename / add branches. Look for any text that
    // identifies it as a branch editor.
    await expect(
      configPanel(page).getByText(/branch/i).first(),
    ).toBeVisible({ timeout: 10_000 });

    // Close the panel before clicking the canvas — its backdrop
    // intercepts canvas pointer events.
    await closeNodeConfig(page);
    await canvasNodes(page, "branch").first().click();
    await page.keyboard.press("Backspace");
    await expect(canvasNodes(page, "branch")).toHaveCount(0);

    expect(
      errors,
      `fatal API errors during branch spec: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
