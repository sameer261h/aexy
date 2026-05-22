/**
 * E2E: Document editor caps the prose container's reading measure.
 *
 * Audit finding (Cluster 2, item a): DocumentEditor.tsx:181 sets
 * `prose max-w-none` on the canvas, so at 1440 px the paragraph
 * measure runs ~140 cpl. Standard for long-form is 60-80 cpl.
 *
 * Expectation after fix: at 1440 viewport, the ProseMirror container's
 * rendered width is ≤ 900 px (some breathing room above max-w-3xl=672
 * to allow tables/code-blocks; cap is firm).
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

test.describe("Docs editor reading measure (live)", () => {
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
          title: `e2e-measure-${Date.now()}`,
          visibility: "workspace",
          content: {
            type: "doc",
            content: [
              {
                type: "paragraph",
                content: [{ type: "text", text: "x".repeat(300) }],
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

  test("ProseMirror canvas is capped at a readable measure on desktop", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });

    const editor = page.locator(".ProseMirror").first();
    await expect(editor).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(500);

    const box = await editor.boundingBox();
    expect(box, "ProseMirror has no bounding box").not.toBeNull();
    expect(
      box!.width,
      `ProseMirror canvas is ${box!.width}px wide on 1440 — uncap was the audit finding; cap to ≤900px`,
    ).toBeLessThanOrEqual(900);
  });
});
