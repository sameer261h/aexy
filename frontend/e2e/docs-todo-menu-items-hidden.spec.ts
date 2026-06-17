/**
 * E2E: TODO menu items (Duplicate, Manage Space) are hidden until they
 * have a real handler.
 *
 * Audit finding (Cluster 1, item d): `NotionSidebar.tsx:113-116` ships
 * `handleDuplicate = console.log("Duplicate:", id)` and similarly for
 * `handleManageSpace`. The corresponding menu entries render in the UI
 * and look clickable, but do nothing. We hide them rather than ship
 * inert affordances.
 *
 * Expectation after fix: the document-row more menu shows Delete (real
 * handler) but does not render Duplicate (no real handler).
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("Docs TODO menu items (live)", () => {
  let docId: string | null = null;

  test.beforeEach(async ({ page, request }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);

    const resp = await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents`,
      {
        headers: authHeaders(),
        data: {
          title: `e2e-menu-${Date.now()}`,
          visibility: "workspace",
          content: { type: "doc", content: [] },
        },
      },
    );
    docId = (await resp.json()).id;
  });

  test.afterEach(async ({ request }) => {
    if (docId) {
      await request
        .delete(
          `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents/${docId}`,
          { headers: authHeaders() },
        )
        .catch(() => {});
      docId = null;
    }
  });

  test("document row more-menu does NOT render Duplicate (inert handler)", async ({
    page,
  }) => {
    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1500);

    const docRow = page.locator(`a[href*="/docs/${docId}"]`).first();
    await expect(docRow).toBeVisible({ timeout: 15_000 });

    const row = docRow.locator("xpath=ancestor::div[contains(@class,'group')][1]");
    await row.hover();
    const moreBtn = row.locator("button:has(svg.lucide-ellipsis), button:has(svg.lucide-more-horizontal)").last();
    await moreBtn.click();

    // Delete should still be there.
    await expect(
      page.getByRole("button", { name: /^delete$/i }).first(),
      "Delete menu item missing — fix would need to keep real handlers visible",
    ).toBeVisible({ timeout: 3_000 });

    // Duplicate should NOT render — its handler is a TODO that
    // console.log()s. Surfacing an inert action is worse than hiding it.
    const dupeItem = page.getByRole("button", { name: /^duplicate$/i });
    await expect(
      dupeItem,
      "Duplicate menu item still rendered — handler is a TODO; hide until implemented",
    ).toHaveCount(0);
  });
});
