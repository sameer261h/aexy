/**
 * E2E: SyncStatusPanel shows the pending-changes banner above the doc
 * when at least one code link has has_pending_changes=true.
 *
 * The panel used to be orphaned (audit finding) — wired into
 * /docs/[documentId]/page.tsx in this same change. This spec locks
 * in the rendering. We intercept the code-links API to seed the
 * pending state, because seeding a real code link requires a
 * Repository row that we'd need to provision separately.
 *
 * Live backend for the doc + auth, mocked code-links call.
 */

import { expect, test } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe("Docs pending-changes banner (live + mocked code-links)", () => {
  test.describe.configure({ timeout: 120_000 });

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
          title: `e2e-pending-${Date.now()}`,
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

  test("banner renders pending-changes count when a code link is dirty", async ({
    page,
  }) => {
    // Intercept the doc-scoped code-links endpoint and return one
    // link flagged dirty. This avoids needing a real Repository row
    // for the FE-only assertion.
    await page.route(
      new RegExp(`/workspaces/${REAL_BACKEND_WORKSPACE_ID}/documents/${docId}/code-links\\b`),
      (route) => {
        if (route.request().method() !== "GET") return route.continue();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "link-pending-1",
              document_id: docId,
              repository_id: "repo-test-1",
              repository_name: "aexy/test",
              path: "src/billing/revenue.ts",
              link_type: "function",
              branch: "main",
              document_section_id: null,
              last_commit_sha: "abc123",
              last_content_hash: "hash-old",
              last_synced_at: null,
              has_pending_changes: true,
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
          ]),
        });
      },
    );

    await page.goto(`/docs/${docId}`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    await expect(page.locator(".ProseMirror").first()).toBeVisible({
      timeout: 30_000,
    });

    // The SyncStatusPanel reports "1 pending change" — pin both the
    // count copy and the manual-sync label (since syncType defaults
    // to "manual" until a per-developer endpoint is exposed).
    await expect(
      page.getByText(/1 pending change/i),
      "pending-changes banner didn't render — SyncStatusPanel may not be wired into the editor page",
    ).toBeVisible({ timeout: 10_000 });

    await expect(
      page.getByText(/manual sync/i).first(),
      "manual sync label missing — SyncStatusPanel mounted with the wrong syncType",
    ).toBeVisible();
  });
});
