/**
 * E2E: Generate from Code → Paste Code tab → new doc landing.
 *
 * Drives the docs landing modal end-to-end: opens it, picks a doc type
 * + language, pastes a function, clicks Generate. Asserts the LLM
 * round-trip succeeds and the user lands on the new document.
 *
 * Live backend + live LM Studio (uses aiLiveReady, not backendOnlyReady).
 */

import { expect, test } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  aiLiveReady,
  authHeaders,
  LLM_WAIT_MS,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe("Docs autogenerate from paste (live)", () => {
  test.describe.configure({ timeout: 300_000 });

  let createdDocId: string | null = null;

  test.beforeEach(async ({ page }) => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test.afterEach(async ({ request }) => {
    if (createdDocId) {
      await request
        .delete(
          `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents/${createdDocId}`,
          { headers: authHeaders() },
        )
        .catch(() => {});
      createdDocId = null;
    }
  });

  test("pasting a TS function generates docs and routes to the new page", async ({
    page,
  }) => {
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1_500);

    // Open the Generate from Code modal via the quick-action card.
    const genCard = page
      .getByRole("button", { name: /generate from code/i })
      .first();
    await expect(genCard).toBeVisible({ timeout: 10_000 });
    await genCard.click();

    // Paste tab is the default. Confirm the source-code textarea is
    // visible, then fill it.
    const textarea = page.getByPlaceholder(/paste your code/i);
    await expect(textarea).toBeVisible({ timeout: 5_000 });
    await textarea.fill(
      [
        "export function gross(amount: number, taxRate: number): number {",
        "  if (taxRate < 0) throw new RangeError('taxRate >= 0');",
        "  return amount * (1 + taxRate);",
        "}",
      ].join("\n"),
    );

    // Capture the new-doc create call so we can grab the id for cleanup.
    const createPromise = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        /\/workspaces\/[^/]+\/documents$/.test(r.url()) &&
        r.status() >= 200 &&
        r.status() < 300,
      { timeout: LLM_WAIT_MS },
    );

    await page
      .getByRole("button", { name: /^generate documentation$/i })
      .last()
      .click();

    const createResp = await createPromise;
    const body = await createResp.json();
    createdDocId = body.id;
    expect(createdDocId, "no id on the created-doc response").toBeTruthy();

    // The page should route into the new doc and render the editor.
    await page.waitForURL(/\/docs\/[0-9a-f-]+/, { timeout: 15_000 });
    await expect(page.locator(".ProseMirror").first()).toBeVisible({
      timeout: 30_000,
    });
  });
});
