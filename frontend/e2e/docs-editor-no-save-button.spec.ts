/**
 * E2E: The redundant Save button is removed from the editor toolbar.
 *
 * Audit finding (Cluster 2, item d): with `autoSave={true}` (the default
 * passed by `[documentId]/page.tsx`), the editor saves on every change
 * after a 1s debounce. The top-right "Save" button at EditorToolbar
 * duplicates this and creates an "is autosave actually working?"
 * doubt loop. Notion, Linear, Craft all drop the manual Save when
 * autosave is on.
 *
 * Expectation after fix: the toolbar at the top of the editor does
 * NOT contain a button whose accessible name matches /^save$/i.
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

test.describe("Docs editor toolbar (live)", () => {
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
          title: `e2e-toolbar-${Date.now()}`,
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

  test("toolbar does not render a redundant Save button when autoSave is on", async ({
    page,
  }) => {
    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await expect(page.locator(".ProseMirror").first()).toBeVisible({
      timeout: 15_000,
    });

    const saveBtn = page.getByRole("button", { name: /^save$/i });
    await expect(
      saveBtn,
      "editor still shows a manual Save button alongside autosave — drop it",
    ).toHaveCount(0);
  });
});
