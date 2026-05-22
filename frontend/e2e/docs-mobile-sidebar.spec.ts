/**
 * E2E: At mobile viewport the docs sidebar must NOT eat the screen.
 *
 * Audit finding (Cluster 1, item b): the sidebar is hard-coded
 * `w-60 flex-shrink-0` with zero responsive variants
 * (`DocsLayoutClient.tsx:136`). At 390×844 it consumes ~62 % of the
 * viewport, pushing the document area off-screen.
 *
 * Expectation after fix:
 *   1. At 390×844 the sidebar is hidden by default (off-screen or
 *      collapsed).
 *   2. A hamburger / menu trigger is visible and labeled.
 *   3. Clicking the trigger reveals the sidebar (drawer pattern).
 *   4. At desktop (1440) the sidebar is visible without any toggle.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("Docs mobile sidebar (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("sidebar is hidden by default at 390px and toggles via hamburger", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(800);

    const sidebar = page.getByTestId("docs-sidebar");
    await expect(
      sidebar,
      "docs sidebar wrapper missing data-testid='docs-sidebar' — add it to the layout root for the drawer container",
    ).toHaveCount(1, { timeout: 10_000 });

    // Hidden state on mobile: the sidebar may be in the DOM but it must
    // NOT consume layout space. We assert the visible bounding-box is
    // either zero-width or off-screen.
    const beforeBox = await sidebar.boundingBox();
    expect(
      beforeBox === null || beforeBox.x + beforeBox.width <= 1 || beforeBox.width <= 1,
      `sidebar visible by default at 390px — box=${JSON.stringify(beforeBox)}`,
    ).toBeTruthy();

    // Mobile menu trigger MUST be present and labeled for assistive tech.
    // The app-shell renders its own fixed-position hamburger at top-left
    // (z-50, Sheet-based), so we target the docs-specific trigger by
    // testid rather than fighting with role-name precedence.
    const menuTrigger = page.getByTestId("docs-mobile-menu-trigger");
    await expect(
      menuTrigger,
      "no docs-scoped mobile menu trigger — add data-testid='docs-mobile-menu-trigger' to the docs hamburger",
    ).toBeVisible({ timeout: 5_000 });
    // Sanity: trigger has an accessible name for SR users.
    const ariaLabel = await menuTrigger.getAttribute("aria-label");
    expect(ariaLabel?.toLowerCase()).toMatch(/docs|sidebar|menu/);

    await menuTrigger.click();
    await page.waitForTimeout(400);

    const afterBox = await sidebar.boundingBox();
    expect(
      afterBox && afterBox.width > 100,
      `sidebar didn't open after clicking the menu trigger — box=${JSON.stringify(afterBox)}`,
    ).toBeTruthy();
  });

  test("sidebar is visible by default at 1440px desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(800);

    const sidebar = page.getByTestId("docs-sidebar");
    await expect(sidebar).toBeVisible({ timeout: 10_000 });
    const box = await sidebar.boundingBox();
    expect(
      box && box.width >= 200,
      `desktop sidebar should be ≥200px wide — box=${JSON.stringify(box)}`,
    ).toBeTruthy();
  });
});
