/**
 * E2E: reviews surface against a REAL backend.
 *
 * Skipped unless `E2E_REAL_BACKEND=1`. Requires:
 *   - `AEXY_TEST_TOKEN` — JWT for an authenticated developer
 *   - `AEXY_TEST_WORKSPACE_ID` — UUID of the workspace they belong to
 *   - `PLAYWRIGHT_BASE_URL` — frontend URL (default http://localhost:3000)
 *   - The frontend's `NEXT_PUBLIC_API_URL` must point at the same
 *     backend (the JWT signature must match the backend's secret).
 *
 * Quick start:
 *   docker exec aexy-backend python scripts/generate_test_token.py --first
 *   # capture the token + the workspace UUID it prints
 *   E2E_REAL_BACKEND=1 \
 *     AEXY_TEST_TOKEN=<jwt> \
 *     AEXY_TEST_WORKSPACE_ID=<uuid> \
 *     PLAYWRIGHT_BASE_URL=http://localhost:3000 \
 *     npx playwright test reviews-live-smoke.spec.ts
 *
 * These tests deliberately exercise the FE→BE contract — they're the
 * line of defense the mocked specs can't provide. Each test asserts
 * either that a real network round-trip succeeds OR that the
 * frontend sends a payload shape the backend's Pydantic schema
 * actually accepts. The latter would have caught the
 * `question_responses: { general: "string" }` 422 in production.
 */

import { test, expect } from "@playwright/test";
import {
  API_BASE,
  setupReviewsMocks,
} from "./fixtures/reviews-mock-data";
import {
  USE_REAL_BACKEND,
  REAL_BACKEND_TOKEN,
  REAL_BACKEND_WORKSPACE_ID,
} from "./fixtures/env";

// Whole file is no-op in mock mode. The single skip avoids polluting
// the default suite with 'skipped' noise.
test.skip(!USE_REAL_BACKEND, "live-only — set E2E_REAL_BACKEND=1 to run");


test.describe("Reviews / live smoke (real backend)", () => {
  test("dashboard /reviews loads without 401 / 5xx", async ({ page }) => {
    // Page-shell tests need a workspace to bootstrap into; contract
    // tests below only need the JWT.
    test.skip(
      !REAL_BACKEND_WORKSPACE_ID,
      "set AEXY_TEST_WORKSPACE_ID to run dashboard tests",
    );
    await setupReviewsMocks(page); // primes real token only — no routes

    // Collect every failed network call so a single bad endpoint
    // gives us a useful error message instead of a generic "page
    // didn't render".
    const failures: { url: string; status: number }[] = [];
    page.on("response", (resp) => {
      const status = resp.status();
      if (status >= 400 && resp.url().includes(API_BASE)) {
        failures.push({ url: resp.url(), status });
      }
    });

    await page.goto("/reviews", { waitUntil: "networkidle", timeout: 30000 });

    // The reviews dashboard heading is the canonical "page rendered"
    // signal — copy may evolve, so we match loosely.
    await expect(
      page.getByRole("heading", { name: /reviews?/i }).first(),
    ).toBeVisible({ timeout: 15000 });

    // No 401s — that'd mean the JWT didn't authenticate. No 5xx —
    // that'd mean a backend bug. 404s on optional endpoints are
    // tolerated (some routes return 404 for "no rows" by design).
    const fatal = failures.filter(
      (f) => f.status === 401 || f.status >= 500,
    );
    expect(
      fatal,
      `fatal API failures during /reviews load: ${JSON.stringify(fatal)}`,
    ).toEqual([]);
  });


  test("POST /reviews/peer-requests/:id/submit accepts the FE payload shape", async ({
    request,
  }) => {
    // Contract test — uses Playwright's APIRequestContext to call
    // the backend directly with the SAME body shape the frontend
    // sends, against a fake request_id. We don't need a real peer
    // request to exist; a 404 means the request_id is unknown but
    // the body validated. A 422 means the schema rejected the body
    // — that's the bug we're guarding against.
    //
    // The frontend sends:
    //   question_responses: { general: { comment: "..." } }
    // The old buggy code sent:
    //   question_responses: { general: "..." }  ← 422
    const fakeRequestId = "00000000-0000-0000-0000-000000000000";
    const fakeReviewerId = "00000000-0000-0000-0000-000000000000";

    const body = {
      responses: {
        achievements: [],
        areas_for_growth: [],
        question_responses: { general: { comment: "smoke test" } },
        strengths: ["x"],
        growth_areas: ["y"],
      },
    };

    const resp = await request.post(
      `${API_BASE}/reviews/peer-requests/${fakeRequestId}/submit?reviewer_id=${fakeReviewerId}`,
      {
        data: body,
        headers: {
          Authorization: `Bearer ${REAL_BACKEND_TOKEN}`,
          "Content-Type": "application/json",
        },
      },
    );

    // 404 (request not found) or 403 (not the reviewer) are
    // contract-valid responses — the schema accepted the body.
    // 422 means Pydantic rejected the body — fail loudly.
    expect(
      resp.status(),
      `submit endpoint returned ${resp.status()} — body: ${await resp.text()}`,
    ).not.toBe(422);
  });


  test("POST /reviews/:id/self-review accepts the FE payload shape", async ({
    request,
  }) => {
    // Same contract test for the self-review endpoint — the same
    // bug shipped to this endpoint as well, so we guard both.
    const fakeReviewId = "00000000-0000-0000-0000-000000000000";

    const body = {
      responses: {
        achievements: [],
        areas_for_growth: [],
        question_responses: { general: { comment: "smoke test" } },
        strengths: ["x"],
        growth_areas: ["y"],
      },
    };

    const resp = await request.post(
      `${API_BASE}/reviews/${fakeReviewId}/self-review`,
      {
        data: body,
        headers: {
          Authorization: `Bearer ${REAL_BACKEND_TOKEN}`,
          "Content-Type": "application/json",
        },
      },
    );

    expect(
      resp.status(),
      `self-review endpoint returned ${resp.status()} — body: ${await resp.text()}`,
    ).not.toBe(422);
  });
});
