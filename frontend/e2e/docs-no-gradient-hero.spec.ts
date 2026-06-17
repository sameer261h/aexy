/**
 * E2E: Regression guard against the AI-slop gradient hero pattern.
 *
 * Audit Pattern A: the literal class string
 *   `from-primary-500/20 to-purple-500/20`
 * paired with `w-16 h-16 rounded-2xl` was the strongest "AI generator
 * empty-state" tell in the docs surface. Two callers used it
 * verbatim (DocsLayoutClient.tsx, page.tsx). This spec locks in
 * their removal: if either re-introduces the gradient, the test fails.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("Docs landing visual (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("/docs landing does not render the gradient-square hero", async ({
    page,
  }) => {
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1_500);

    const html = await page.content();
    expect(
      html.includes("from-primary-500/20 to-purple-500/20"),
      "found the AI-slop gradient hero on the docs landing — replace with a typography-first treatment",
    ).toBe(false);

    // Also assert no `w-16 h-16 rounded-2xl` decorative icon container
    // on the page; that's the second half of the pattern. A genuine
    // 16×16 rounded square elsewhere (a sidebar item etc.) wouldn't
    // typically combine all three utilities.
    const decorativeSquare = page.locator(
      'div.w-16.h-16.rounded-2xl',
    );
    expect(
      await decorativeSquare.count(),
      "decorative w-16 h-16 rounded-2xl square is back on /docs — likely the gradient hero is back too",
    ).toBe(0);
  });
});
