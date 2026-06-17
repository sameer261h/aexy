/**
 * E2E: SearchModal exposes the right ARIA contract.
 *
 * Audit finding (Cluster 3, item a): the docs surface has zero
 * role/aria-modal/aria-label declarations across 6,585 LOC. The
 * SearchModal mounted via Cmd+K is the most-used overlay — needs
 * role="dialog", aria-modal, and an accessible label so screen-reader
 * users can identify it.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("Docs SearchModal a11y (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("SearchModal has role=dialog + aria-modal + aria-label", async ({
    page,
  }) => {
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1_000);
    await page.keyboard.press(process.platform === "darwin" ? "Meta+K" : "Control+K");

    // Wait for the doc-scoped search input to appear (proves the
    // capture-phase interception did its job).
    await expect(page.getByPlaceholder(/search documents/i)).toBeVisible({
      timeout: 5_000,
    });

    // The modal root must be a dialog with aria-modal=true and a
    // non-empty accessible label.
    const dialog = page.getByRole("dialog").filter({ has: page.getByPlaceholder(/search documents/i) }).first();
    await expect(
      dialog,
      "SearchModal isn't marked role='dialog' — assistive tech can't identify it as an overlay",
    ).toBeVisible({ timeout: 3_000 });

    const ariaModal = await dialog.getAttribute("aria-modal");
    expect(ariaModal, "aria-modal missing on SearchModal").toBe("true");

    const label =
      (await dialog.getAttribute("aria-label")) ??
      (await dialog.getAttribute("aria-labelledby"));
    expect(
      label,
      "SearchModal has no aria-label or aria-labelledby — add a descriptive label",
    ).toBeTruthy();
  });
});
