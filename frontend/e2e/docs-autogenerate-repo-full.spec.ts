/**
 * E2E: Generate from Code → From Repository tab → full UI orchestration.
 *
 * Drives the modal end-to-end:
 *   1. List repositories  → mocked (one entry pointing at a public repo)
 *   2. Pick repo → list branches  → mocked
 *   3. Browse contents → pick a file  → mocked
 *   4. Click Generate → calls /generate-from-repository  → mocked
 *      (returns canned TipTap JSON; the LLM is exercised at the service
 *       layer in test_document_generation_repo.py, and the live LLM
 *       round-trip is exercised by docs-autogenerate-paste.spec.ts)
 *   5. New doc created → frontend routes to /docs/<id>
 *
 * Why mocks at the API boundary instead of a real-GitHub pull-through:
 * the workspace under test has no GitHub installation, so a real fetch
 * would 4xx with no useful coverage. The orchestration (modal UX,
 * tree browser, tab state, generate-button enablement, post-create
 * routing) is what's exercised here.
 *
 * Live backend for auth + doc creation, mocked for repo/branch/content
 * listing and the generate endpoint.
 */

import { expect, test } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe("Docs autogenerate from repository — full UI flow", () => {
  test.describe.configure({ timeout: 180_000 });

  let createdDocId: string | null = null;

  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
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

  test("user picks a public repo, navigates to a file, generates", async ({
    page,
  }) => {
    const FAKE_REPO_ID = "repo-octocat-1";

    // ── repositoriesApi.listRepositories({enabled_only: true}) ──
    await page.route(/\/repositories(\?.*)?$/, (route) => {
      const method = route.request().method();
      const url = route.request().url();
      if (method !== "GET" || !/enabled_only=true/.test(url)) {
        return route.continue();
      }
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([
          {
            id: FAKE_REPO_ID,
            full_name: "octocat/Hello-World",
            name: "Hello-World",
            description: "Public sample repo used in the docs autogenerate E2E.",
            language: "JavaScript",
            default_branch: "master",
            private: false,
          },
        ]),
      });
    });

    // ── repositoriesApi.getBranches(repoId) ──
    await page.route(
      new RegExp(`/repositories/${FAKE_REPO_ID}/branches\\b`),
      (route) => {
        if (route.request().method() !== "GET") return route.continue();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            { name: "master", commit_sha: "deadbeef", protected: false },
          ]),
        });
      },
    );

    // ── repositoriesApi.getContents(repoId, {path, ref}) ──
    await page.route(
      new RegExp(`/repositories/${FAKE_REPO_ID}/contents\\b`),
      (route) => {
        if (route.request().method() !== "GET") return route.continue();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              name: "README",
              path: "README",
              type: "file",
              size: 13,
              sha: "abc",
            },
          ]),
        });
      },
    );

    // ── POST /workspaces/{ws}/documents/generate-from-repository ──
    // Return a canned TipTap doc so the frontend's downstream
    // create-document call has content to write.
    const GENERATED = {
      type: "doc",
      content: [
        {
          type: "heading",
          attrs: { level: 1 },
          content: [{ type: "text", text: "Hello-World / README" }],
        },
        {
          type: "paragraph",
          content: [
            {
              type: "text",
              text: "Sample documentation generated from octocat/Hello-World#master:README.",
            },
          ],
        },
      ],
    };
    await page.route(
      /\/documents\/generate-from-repository\b/,
      (route) => {
        if (route.request().method() !== "POST") return route.continue();
        return route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            status: "success",
            content: GENERATED,
          }),
        });
      },
    );

    await page.goto("/docs", { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1_500);

    // Open the Generate from Code modal, switch to From Repository.
    await page.getByRole("button", { name: /generate from code/i }).first().click();
    await page.getByRole("button", { name: /from repository/i }).first().click();

    // The mocked repo card should appear.
    const repoCard = page.getByText(/octocat\/Hello-World/i).first();
    await expect(
      repoCard,
      "mocked repository didn't render — the listRepositories mock didn't bind",
    ).toBeVisible({ timeout: 10_000 });
    await repoCard.click();

    // README file row appears in the tree (mocked getContents). The
    // modal's UX is "navigate into directories, generate against the
    // current path" — file rows are intentionally disabled (see
    // page.tsx:741). Just confirming the file row renders, then we
    // generate against the root (currentPath = "").
    await expect(
      page.locator("button", { hasText: /^README$/ }).first(),
    ).toBeVisible({ timeout: 10_000 });

    // Click Generate. Capture the create-doc POST so we can grab the
    // id for cleanup. The create call hits the LIVE backend.
    const createPromise = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        /\/workspaces\/[^/]+\/documents$/.test(r.url()) &&
        r.status() >= 200 &&
        r.status() < 300,
      { timeout: 60_000 },
    );

    await page
      .getByRole("button", { name: /^generate documentation$/i })
      .last()
      .click();

    const createResp = await createPromise;
    const body = await createResp.json();
    createdDocId = body.id;
    expect(createdDocId, "no id on the created-doc response").toBeTruthy();

    // FE routes to the new doc; editor mounts.
    await page.waitForURL(/\/docs\/[0-9a-f-]+/, { timeout: 15_000 });
    await expect(page.locator(".ProseMirror").first()).toBeVisible({
      timeout: 30_000,
    });

    // The generated content (mocked) should be present in the doc.
    await expect(
      page.getByText(/Hello-World \/ README/i),
      "generated content didn't make it into the rendered doc",
    ).toBeVisible({ timeout: 10_000 });
  });
});
