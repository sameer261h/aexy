/**
 * E2E: A floating BubbleMenu appears when text is selected.
 *
 * Audit finding (Cluster 2, item e): the BubbleMenu is implemented in
 * `CollaborativeEditor.tsx:388-430` but lives behind a
 * `collaborationEnabled` flag that is hardcoded `false`. Users on the
 * non-collab editor path (`DocumentEditor.tsx`) have no floating
 * formatting toolbar — only the always-on top toolbar.
 *
 * Expectation after fix: selecting text in the editor reveals a
 * floating menu with at least Bold + Italic options near the
 * selection.
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

test.describe("Docs editor bubble menu (live)", () => {
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
          title: `e2e-bubble-${Date.now()}`,
          visibility: "workspace",
          content: {
            type: "doc",
            content: [
              {
                type: "paragraph",
                content: [
                  {
                    type: "text",
                    text: "Select this paragraph to test the floating bubble menu.",
                  },
                ],
              },
            ],
          },
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

  test("selecting text reveals a floating BubbleMenu with B + I controls", async ({
    page,
  }) => {
    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    const editor = page.locator(".ProseMirror").first();
    await expect(editor).toBeVisible({ timeout: 15_000 });

    // Triple-click the paragraph to select it. Cmd+A on the focused
    // ProseMirror collapses the selection rect in some configurations
    // and tippy's positioning then drops the bubble. Triple-click
    // produces a real text-range selection with a non-empty rect.
    const para = page.locator(".ProseMirror p").first();
    await para.click({ clickCount: 3 });
    await page.waitForTimeout(600);

    // The BubbleMenu mounts as a [data-testid="docs-bubble-menu"]
    // container. Implementation must set that attribute on the menu
    // root so the audit can be regression-tested.
    const bubble = page.getByTestId("docs-bubble-menu");
    await expect(
      bubble,
      "no floating BubbleMenu after selecting text — non-collab editor path needs the menu wired in",
    ).toBeVisible({ timeout: 5_000 });

    await expect(bubble.getByRole("button", { name: /bold/i }).first()).toBeVisible();
    await expect(bubble.getByRole("button", { name: /italic/i }).first()).toBeVisible();
  });
});
