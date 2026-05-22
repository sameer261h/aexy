/**
 * E2E: Generate from Code → From Repository tab.
 *
 * The full generate-from-repo LLM round trip is covered at the
 * service layer (`backend/tests/ai/services/test_document_generation_repo.py`)
 * because spinning up a seeded repository inside a workspace just to
 * drive the UI is a 5-step ceremony that's brittle and slow.
 *
 * This spec focuses on the FRONTEND wiring: the tab opens, the
 * repository-fetcher panel mounts, and the user sees either the
 * connected-repos list or the "no repositories connected" empty
 * state with a clear next-action.
 *
 * Live backend, no LLM (uses backendOnlyReady).
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";

test.describe("Docs autogenerate from repository — UI wiring (live)", () => {
  test.describe.configure({ timeout: 120_000 });

  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test("From Repository tab is reachable and shows a clear state", async ({ page }) => {
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1_500);

    // Open the Generate from Code modal.
    await page.getByRole("button", { name: /generate from code/i }).first().click();

    // Switch to the From Repository tab.
    const repoTab = page.getByRole("button", { name: /from repository/i }).first();
    await expect(repoTab).toBeVisible({ timeout: 5_000 });
    await repoTab.click();

    // Either the connected-repos list renders, or the empty state
    // does — both are valid. The Generate button MUST be disabled
    // until a repo is picked (no half-broken UX).
    const emptyState = page.getByText(/no repositories connected/i);
    const repoList = page.locator("[data-testid='repo-list-item'], button:has(svg.lucide-folder-git2)");

    const hasEmpty = await emptyState.isVisible({ timeout: 3_000 }).catch(() => false);
    const hasList = (await repoList.count()) > 0;

    expect(
      hasEmpty || hasList,
      "From Repository tab rendered neither the empty state nor a repo list — UI is broken",
    ).toBe(true);

    // Generate button is rendered but disabled until a path is selected.
    const generateBtn = page
      .getByRole("button", { name: /^generate documentation$/i })
      .last();
    await expect(generateBtn).toBeVisible();
    if (hasEmpty) {
      await expect(
        generateBtn,
        "Generate button should be disabled when no repositories are connected",
      ).toBeDisabled();
    }
  });
});
