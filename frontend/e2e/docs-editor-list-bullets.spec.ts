/**
 * E2E: Bullet lists in the editor render with visible markers.
 *
 * Audit finding (Cluster 2, item b): the inline `prose` className on
 * the ProseMirror container at DocumentEditor.tsx:411 misses
 * `prose-ul:list-disc prose-ul:pl-6` (and the ordered-list equivalent),
 * so Tailwind's `list-style: none` reset wins and list items render as
 * plain paragraphs with no bullets.
 *
 * Expectation after fix: a `<ul>` inside the ProseMirror has computed
 * `list-style-type` of "disc" (or a non-"none" visible marker), and
 * the list items are visibly indented.
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

test.describe("Docs editor list rendering (live)", () => {
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
          title: `e2e-bullets-${Date.now()}`,
          visibility: "workspace",
          content: {
            type: "doc",
            content: [
              {
                type: "bulletList",
                content: [
                  {
                    type: "listItem",
                    content: [
                      { type: "paragraph", content: [{ type: "text", text: "First" }] },
                    ],
                  },
                  {
                    type: "listItem",
                    content: [
                      { type: "paragraph", content: [{ type: "text", text: "Second" }] },
                    ],
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

  test("<ul> inside ProseMirror has a visible bullet marker", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    const ul = page.locator(".ProseMirror ul").first();
    await expect(ul).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(300);

    const listStyleType = await ul.evaluate(
      (el) => getComputedStyle(el as HTMLElement).listStyleType,
    );
    expect(
      ["none", "", null].includes(listStyleType),
      `bulletList <ul> has list-style-type "${listStyleType}" — the prose styling drops bullets`,
    ).toBe(false);

    // Items should be indented from the list-item perspective (padding
    // or margin gives the marker space to render). Check the first li.
    const li = page.locator(".ProseMirror ul > li").first();
    const liBox = await li.boundingBox();
    const ulBox = await ul.boundingBox();
    expect(
      liBox && ulBox && liBox.x >= ulBox.x,
      "list item didn't indent inside the ul — the prose padding may be missing",
    ).toBeTruthy();
  });
});
