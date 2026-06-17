/**
 * E2E: Sub-routes under /docs render usable content at 390px mobile.
 *
 * Audit Pattern F: only 13 responsive utility usages in 6,585 LOC.
 * Drive / Files / Knowledge-Graph each got a targeted pass; this
 * spec locks in that the primary content area is visible (not
 * stranded behind the sidebar or stuck on a perpetual spinner).
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe("Docs mobile sub-routes (live)", () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await page.setViewportSize({ width: 390, height: 844 });
    await setupAiLiveAuth(page);
  });

  test("/docs/drive renders the Files & Storage page on mobile", async ({ page }) => {
    await page.goto("/docs/drive", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(2_000);

    const heading = page.getByRole("heading", { name: /files.*storage|storage.*files/i }).first();
    await expect(heading, "Drive heading not visible at 390px").toBeVisible({ timeout: 10_000 });

    const box = await heading.boundingBox();
    expect(box, "Drive heading has no bounding box").not.toBeNull();
    expect(
      box!.x >= 0 && box!.x + box!.width <= 400,
      `Drive heading is off-screen at 390px (x=${box?.x}, w=${box?.width})`,
    ).toBe(true);
  });

  test("/docs/knowledge-graph paywall is readable on mobile", async ({ page }) => {
    await page.goto("/docs/knowledge-graph", {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await page.waitForTimeout(2_000);

    const heading = page.getByRole("heading", { name: /knowledge graph/i }).first();
    await expect(heading).toBeVisible({ timeout: 10_000 });

    // The CTA may render as a Link (anchor) rather than a button.
    const upgradeCta = page
      .getByRole("link", { name: /upgrade/i })
      .or(page.getByRole("button", { name: /upgrade/i }))
      .first();
    await expect(upgradeCta).toBeVisible();
    const box = await upgradeCta.boundingBox();
    expect(
      box && box.x >= 0 && box.x + box.width <= 400,
      `Upgrade CTA overflows at 390px (x=${box?.x}, w=${box?.width})`,
    ).toBeTruthy();
  });

  test("/docs/files redirects to /docs/drive instead of stranding the user", async ({
    page,
  }) => {
    await page.goto("/docs/files", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(2_000);
    // Should now match the Drive page (because /docs/files redirects).
    await expect(
      page.getByRole("heading", { name: /files.*storage/i }).first(),
    ).toBeVisible({ timeout: 10_000 });
  });
});
