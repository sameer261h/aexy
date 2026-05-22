/**
 * E2E: Document-editor emoji picker closes when the user presses Escape.
 *
 * Audit finding (Cluster 2, item c): the icon picker at
 * DocumentEditor.tsx:318-342 has no Escape handler — only a backdrop
 * click and the toggle button close it. Confirmed visually in the
 * audit screenshots where the picker stayed open across three other
 * actions.
 *
 * Expectation after fix: pressing Escape with the picker open hides it.
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

test.describe("Docs editor emoji picker (live)", () => {
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
          title: `e2e-emoji-${Date.now()}`,
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

  test("Escape closes the icon picker", async ({ page }) => {
    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    const iconBtn = page.locator('button[title="Change icon"]').first();
    await expect(iconBtn).toBeVisible({ timeout: 15_000 });
    await iconBtn.click();

    // Picker is identified by its header copy.
    const pickerHeader = page.getByText(/choose an icon/i);
    await expect(pickerHeader).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Escape");

    await expect(
      pickerHeader,
      "icon picker stayed open after Escape — the keydown handler isn't wired",
    ).toBeHidden({ timeout: 3_000 });
  });
});
