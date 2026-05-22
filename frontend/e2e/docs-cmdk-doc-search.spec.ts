/**
 * E2E: Cmd+K in /docs opens the doc-scoped SearchModal, not the global
 * CommandPalette.
 *
 * Audit finding (Cluster 1, item a): the docs sidebar advertises a
 * `Cmd K` shortcut but the global CommandPalette intercepts the keypress
 * (both listeners run on `document`, the global is mounted earlier in the
 * app shell at `/app/(app)/layout.tsx:75`). Users hitting Cmd+K in /docs
 * see "Search commands, navigate, or type..." with results like "New
 * Ticket" — they never reach the documents search.
 *
 * Failing today; expected to pass once the docs layout's keybinding fires
 * in capture phase and stopImmediatePropagation()s the global handler.
 *
 * Live backend, no LLM (uses backendOnlyReady).
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("Docs Cmd+K (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("Cmd+K in /docs opens doc-scoped search, not the global palette", async ({
    page,
  }) => {
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    // Give the layout listener a tick to bind.
    await page.locator(".w-60, aside").first().waitFor({ timeout: 15_000 });
    await page.waitForTimeout(500);

    await page.keyboard.press(process.platform === "darwin" ? "Meta+K" : "Control+K");

    // Doc search: SearchModal renders an input with placeholder "Search documents...".
    const docSearch = page.getByPlaceholder(/search documents/i);
    await expect(
      docSearch,
      "doc-scoped SearchModal didn't open — Cmd+K is still routed to the global palette",
    ).toBeVisible({ timeout: 5_000 });

    // Global palette MUST NOT be visible at the same time. Its
    // placeholder is "Search commands, navigate, or type...".
    const globalPalette = page.getByPlaceholder(/search commands, navigate/i);
    await expect(
      globalPalette,
      "global CommandPalette opened too — capture-phase interception didn't stop it",
    ).toBeHidden();
  });
});
