/**
 * E2E: Join node — render + multiple input handles + join_type config.
 *
 * Join has 3 subtypes (all / any / count) — we exercise `all` because
 * it's the default and most common. The node must render ≥2 target
 * handles so two upstream branches can converge.
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

test.describe("AI / Automation node: join (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("adds a join (all) with ≥2 input handles, configures, deletes", async ({
    page,
  }) => {
    const errors = collectFatalApiErrors(page);
    await openCanvas(page, { module: "crm" });

    await addNodeFromPalette(page, "join", "all");

    const joinNodes = canvasNodes(page, "join");
    await expect(joinNodes).toHaveCount(1);
    await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

    // Defaults: incoming_branches=2 (see WorkflowCanvas.tsx:564). The
    // node should render ≥2 target handles so the user can wire two
    // upstream branches into it. ReactFlow tags handles with the CSS
    // class `source` / `target`, not a data-handletype attribute.
    const node = joinNodes.first();
    const targetHandles = node.locator(".react-flow__handle.target");
    expect(
      await targetHandles.count(),
      "join node must expose ≥2 target handles to be useful",
    ).toBeGreaterThanOrEqual(2);

    // Config panel should mention "join" or the join_type setting.
    await expect(
      configPanel(page).getByText(/join|wait.*all|wait.*any|count/i).first(),
    ).toBeVisible({ timeout: 10_000 });

    // Re-open via click-to-select.
    await closeNodeConfig(page);
    await openNodeConfig(page, "join");
    await expect(configPanel(page)).toBeVisible();

    // Delete.
    await closeNodeConfig(page);
    await canvasNodes(page, "join").first().click();
    await page.keyboard.press("Backspace");
    await expect(canvasNodes(page, "join")).toHaveCount(0);

    expect(
      errors,
      `fatal API errors during join spec: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
