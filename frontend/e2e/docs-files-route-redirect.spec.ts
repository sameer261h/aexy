/**
 * E2E: Bare `/docs/files` doesn't strand the user on an infinite "Loading
 * document..." spinner.
 *
 * Audit finding (Cluster 1, item e): `/docs/files/[sourceType]/[sourceId]`
 * is a valid sub-route, but navigating to the bare prefix `/docs/files`
 * matches the `[documentId]` route with `documentId = "files"`, which
 * the editor then loads forever waiting for a document that doesn't
 * exist. The user is stuck.
 *
 * Expectation after fix: navigating to `/docs/files` either redirects
 * to `/docs/drive` (or `/docs`) or renders an explicit not-found state.
 * It must NOT show "Loading document..." indefinitely.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("Docs /files bare-route handling (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("/docs/files does not strand on a perpetual loading spinner", async ({
    page,
  }) => {
    await page.goto("/docs/files", { waitUntil: "domcontentloaded", timeout: 60_000 });
    // Give Next.js dev compile + any redirect a chance to settle.
    await page.waitForTimeout(2_500);

    // After settle: either we got redirected away from /docs/files, or
    // we're still on it but showing real content (not the editor's
    // "Loading document..." placeholder).
    const finalUrl = page.url();
    const loadingDoc = page.getByText(/^loading document\.\.\.$/i);

    const stuckLoading = await loadingDoc.isVisible().catch(() => false);
    const redirected = !finalUrl.match(/\/docs\/files\/?$/);

    expect(
      redirected || !stuckLoading,
      `Bare /docs/files stranded the user on a "Loading document..." spinner ` +
        `(url=${finalUrl}). The fix should redirect away from /docs/files or render an explicit not-found.`,
    ).toBe(true);
  });
});
