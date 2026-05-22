/**
 * E2E: Drive surface is reachable from the docs sidebar and is
 * labeled clearly enough that a user can tell it's separate from
 * docs.
 *
 * Audit finding: `/docs/drive` was a file uploader nested under
 * `/docs/` with no entry in the docs sidebar. Users reached it only
 * by URL and saw a page titled just "Drive" with no context.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("Docs Drive IA (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("sidebar exposes a 'Files' link that lands on the Files & Storage page", async ({
    page,
  }) => {
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1_500);

    const filesLink = page.getByRole("link", { name: /^files$/i }).first();
    await expect(
      filesLink,
      "no 'Files' link in the docs sidebar — Drive used to be reachable only by URL",
    ).toBeVisible({ timeout: 10_000 });

    await filesLink.click();
    await page.waitForURL(/\/docs\/drive(\/|$|\?)/, { timeout: 15_000 });

    // The page title and subtitle must disambiguate this surface from
    // the writing-focused docs.
    await expect(
      page.getByRole("heading", { name: /files.*storage|storage.*files/i }),
      "Drive page heading still reads bare 'Drive' — rename to disambiguate from docs",
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText(/separate from your written docs/i),
      "Drive page subtitle missing the disambiguating copy",
    ).toBeVisible();
  });
});
