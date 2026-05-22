/**
 * E2E: Deleting a document opens a styled confirmation dialog, not the
 * native `window.confirm()`.
 *
 * Audit finding (Cluster 1, item c): `NotionSidebar.tsx:104`,
 * `DocumentSidebar.tsx:81`, and `CodeLinksDisplay.tsx:43` all use the
 * browser-native confirm dialog, which is jarring against the styled
 * dark theme.
 *
 * Expectation after fix:
 *   - Triggering delete opens a styled dialog (role=dialog) with
 *     Cancel + Delete buttons.
 *   - Cancel closes the dialog without deleting.
 *   - The native browser confirm is never invoked (no dialog handler
 *     fired).
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

test.describe("Docs delete confirm dialog (live)", () => {
  let createdDocId: string | null = null;

  test.beforeEach(async ({ page, request }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);

    // Seed a shared doc the sidebar will surface.
    const resp = await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents`,
      {
        headers: authHeaders(),
        data: {
          title: `e2e-confirm-${Date.now()}`,
          visibility: "workspace",
          content: { type: "doc", content: [] },
        },
      },
    );
    expect(resp.ok(), `seed doc failed: ${resp.status()}`).toBeTruthy();
    const body = await resp.json();
    createdDocId = body.id;
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

  test("delete uses a styled dialog and Cancel preserves the document", async ({
    page,
  }) => {
    // If the implementation ever falls back to window.confirm(), the
    // dialog handler below auto-dismisses with "cancel" — and would also
    // record the message in `dialogMessages`. The post-condition asserts
    // no native dialogs fired.
    const dialogMessages: string[] = [];
    page.on("dialog", async (dialog) => {
      dialogMessages.push(dialog.message());
      await dialog.dismiss();
    });

    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1500); // sidebar load

    const docRow = page.locator(`a[href*="/docs/${createdDocId}"]`).first();
    await expect(
      docRow,
      "seeded doc didn't show up in the sidebar within 15s",
    ).toBeVisible({ timeout: 15_000 });

    // Hover the row to reveal the action cluster, then click the
    // "more" trigger (lucide MoreHorizontal). DocumentItem renders it
    // without a stable testid today; we target via the closest button
    // that has the more-horizontal SVG.
    const row = docRow.locator("xpath=ancestor::div[contains(@class,'group')][1]");
    await row.hover();
    const moreBtn = row.locator("button:has(svg.lucide-ellipsis), button:has(svg.lucide-more-horizontal)").last();
    await moreBtn.click();

    const deleteItem = page.getByRole("button", { name: /^delete$/i }).first();
    await expect(deleteItem).toBeVisible({ timeout: 5_000 });
    await deleteItem.click();

    // Styled dialog must appear. role=dialog + an aria-label/heading
    // that mentions delete is the minimum contract.
    const confirmDialog = page.getByRole("dialog").filter({ hasText: /delete/i }).first();
    await expect(
      confirmDialog,
      "no styled confirm dialog appeared — delete still uses native confirm()",
    ).toBeVisible({ timeout: 5_000 });

    // No native dialog should have fired.
    expect(
      dialogMessages,
      `native window.confirm() fired: ${JSON.stringify(dialogMessages)}`,
    ).toEqual([]);

    // Cancel preserves the doc.
    await confirmDialog.getByRole("button", { name: /^cancel$/i }).click();
    await expect(confirmDialog).toBeHidden({ timeout: 3_000 });
    await expect(docRow, "doc was deleted on Cancel").toBeVisible();
  });
});
