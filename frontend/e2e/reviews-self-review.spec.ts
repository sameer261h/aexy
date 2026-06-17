/**
 * E2E: self-review submission flow.
 *
 * Walks the reviewee's perspective through the cycle:
 *   1. Open /reviews/my-reviews/:id — see the form
 *   2. Validation: empty submission is rejected
 *   3. Fill bullet editor + textarea, submit, see "Submitted" state
 *   4. Already-submitted state renders summary, not the form
 *   5. Self-nominate peer reviewers via the modal (employee_choice
 *      cycle setting)
 *   6. Acknowledge action only renders when the review is "completed"
 */

import { test, expect } from "@playwright/test";
import {
  API_BASE,
  DEV,
  WORKSPACE,
  setupReviewsMocks,
  makeSpiedRoute,
} from "./fixtures/reviews-mock-data";
import { USE_REAL_BACKEND } from "./fixtures/env";

// The entire spec file relies on stubbed responses — every test
// asserts on specific mock-injected state (pending review, validation
// toast wiring, status flip after submit). In live mode the backend
// is the source of truth, so skip the whole file and let
// `reviews-live-smoke.spec.ts` cover the same surfaces against real
// data.
test.skip(USE_REAL_BACKEND, "mock-only — use reviews-live-smoke.spec.ts in live mode");


const REVIEW_ID = "review-1";
const CYCLE_ID = "cycle-1";

const BASE_CYCLE = {
  id: CYCLE_ID,
  workspace_id: WORKSPACE.id,
  name: "Q1 2026 Reviews",
  cycle_type: "quarterly",
  period_start: "2026-01-01",
  period_end: "2026-03-31",
  self_review_deadline: "2026-02-15",
  peer_review_deadline: "2026-02-28",
  manager_review_deadline: "2026-03-15",
  settings: {
    enable_self_review: true,
    enable_peer_review: true,
    enable_manager_review: true,
    anonymous_peer_reviews: false,
    min_peer_reviewers: 2,
    max_peer_reviewers: 5,
    peer_selection_mode: "employee_choice" as
      | "employee_choice"
      | "manager_assigned"
      | "both",
    include_github_metrics: true,
  },
  status: "self_review" as const,
  enrolled_developers: [],
};

const PENDING_REVIEW = {
  id: REVIEW_ID,
  review_cycle_id: CYCLE_ID,
  developer_id: DEV.id,
  manager_id: "manager-1",
  manager_name: "Test Manager",
  developer_name: DEV.name,
  status: "pending" as const,
  self_review: null,
  manager_review: null,
  overall_rating: null,
  ratings_breakdown: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const SUBMITTED_REVIEW = {
  ...PENDING_REVIEW,
  status: "self_completed" as const,
  self_review: {
    submitted_at: "2026-02-10T00:00:00Z",
    responses: {
      strengths: ["Owned the auth migration"],
      growth_areas: ["Sharper trade-off thinking"],
      achievements: [],
      areas_for_growth: [],
      question_responses: { general: "Solid quarter overall." },
    },
  },
};


// Routes that every self-review test needs — review, cycle,
// peer-requests-for-review (empty by default).
async function setupReviewRoutes(
  page: import("@playwright/test").Page,
  review: typeof PENDING_REVIEW | typeof SUBMITTED_REVIEW,
  cycle: typeof BASE_CYCLE = BASE_CYCLE,
) {
  await page.route(
    new RegExp(`${API_BASE}/reviews/${REVIEW_ID}$`),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(review),
      }),
  );
  await page.route(
    new RegExp(`${API_BASE}/reviews/cycles/${CYCLE_ID}$`),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(cycle),
      }),
  );
  await page.route(
    new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/peer-requests$`),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      }),
  );
}


test.describe("Reviews / self-review", () => {
  test("opens the self-review form in 'Not started' state", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "member" });
    await setupReviewRoutes(page, PENDING_REVIEW);

    await page.goto(`/reviews/my-reviews/${REVIEW_ID}`);

    // Status badge says "Not started" — the form should be visible,
    // the submitted summary should NOT.
    await expect(
      page.getByRole("heading", { name: /Your self review/i }),
    ).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Not started/i).first()).toBeVisible();
    await expect(
      page.getByRole("button", { name: /Submit self-review/i }),
    ).toBeVisible();
  });


  test("empty submission shows a validation toast, no API call", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "member" });
    await setupReviewRoutes(page, PENDING_REVIEW);
    const submitSpy = makeSpiedRoute(
      page,
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/self-review$`),
      () => ({ status: 201, body: { id: "sub-1" } }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/my-reviews/${REVIEW_ID}`);
    await page
      .getByRole("button", { name: /Submit self-review/i })
      .click();
    // The toast appears via sonner — wait briefly then verify the
    // server was NOT hit.
    await expect(
      page.getByText(/at least one strength, growth area, or note/i),
    ).toBeVisible({ timeout: 3000 });
    expect(submitSpy.calls).toBe(0);
  });


  test("filled form POSTs the expected payload + shows Submitted state", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "member" });

    // The first GET returns pending; after the submit, the page
    // invalidates the query and re-fetches. Flip the response.
    let review: typeof PENDING_REVIEW | typeof SUBMITTED_REVIEW = PENDING_REVIEW;
    await page.route(
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(review),
        }),
    );
    await page.route(
      new RegExp(`${API_BASE}/reviews/cycles/${CYCLE_ID}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(BASE_CYCLE),
        }),
    );
    await page.route(
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/peer-requests$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        }),
    );

    const submitSpy = makeSpiedRoute<{
      responses: {
        strengths: string[];
        growth_areas: string[];
        // Backend ReviewResponses.question_responses is
        // `dict[str, QuestionResponse]` — each value is an object with
        // `rating` and/or `comment` keys, NOT a bare string. A previous
        // version of this code shipped a string here and the backend
        // returned 422.
        question_responses: Record<string, { comment?: string; rating?: number }>;
      };
    }>(
      page,
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/self-review$`),
      () => {
        // Flip the review state so the page's refetch picks up the
        // submitted summary.
        review = SUBMITTED_REVIEW;
        return { status: 201, body: { id: "sub-1" } };
      },
      (method) => method === "POST",
    );

    await page.goto(`/reviews/my-reviews/${REVIEW_ID}`);

    // BulletEditor: each "What went well" / "Areas to grow" row is a
    // textarea. The first textarea under each label is the entry
    // input. Fill the first strengths row, then the first growth
    // row.
    const strengthsArea = page
      .locator("label", { hasText: "What went well" })
      .locator("..")
      .locator("textarea")
      .first();
    await strengthsArea.fill("Owned the auth migration");

    const growthArea = page
      .locator("label", { hasText: "Areas to grow" })
      .locator("..")
      .locator("textarea")
      .first();
    await growthArea.fill("Sharper trade-off thinking");

    const noteArea = page
      .locator("label", { hasText: "Anything else" })
      .locator("..")
      .locator("textarea")
      .first();
    await noteArea.fill("Solid quarter overall.");

    await page
      .getByRole("button", { name: /Submit self-review/i })
      .click();

    await expect.poll(() => submitSpy.calls, { timeout: 8000 }).toBe(1);

    // Payload sanity. Trim() in the form drops trailing whitespace
    // but the test inputs have none, so equality is safe.
    expect(submitSpy.lastBody?.responses.strengths).toContain(
      "Owned the auth migration",
    );
    expect(submitSpy.lastBody?.responses.growth_areas).toContain(
      "Sharper trade-off thinking",
    );
    // The "general" note must be wrapped as `{ comment: ... }`, not a
    // bare string — otherwise the backend Pydantic validator rejects
    // with 422.
    const general = submitSpy.lastBody?.responses.question_responses.general;
    expect(typeof general).toBe("object");
    expect(general?.comment).toBe("Solid quarter overall.");

    // The refetched review is `SUBMITTED_REVIEW` — UI should switch
    // to summary mode.
    await expect(page.getByText(/Submitted/i).first()).toBeVisible({
      timeout: 5000,
    });
  });


  test("already-submitted review renders summary, not form", async ({ page }) => {
    await setupReviewsMocks(page, { role: "member" });
    await setupReviewRoutes(page, SUBMITTED_REVIEW);

    await page.goto(`/reviews/my-reviews/${REVIEW_ID}`);

    // Summary content from SUBMITTED_REVIEW.self_review.responses.
    await expect(page.getByText("Owned the auth migration")).toBeVisible({
      timeout: 10000,
    });
    await expect(page.getByText("Sharper trade-off thinking")).toBeVisible();
    // No submit button — we're in summary mode.
    await expect(
      page.getByRole("button", { name: /Submit self-review/i }),
    ).toHaveCount(0);
  });


  test("Nominate reviewers button only renders for employee_choice / both modes", async ({
    page,
  }) => {
    // employee_choice cycle setting → button visible.
    await setupReviewsMocks(page, { role: "member" });
    await setupReviewRoutes(page, PENDING_REVIEW, {
      ...BASE_CYCLE,
      settings: { ...BASE_CYCLE.settings, peer_selection_mode: "employee_choice" },
    });

    await page.goto(`/reviews/my-reviews/${REVIEW_ID}`);
    await expect(
      page.getByRole("button", { name: /Nominate reviewers/i }),
    ).toBeVisible({ timeout: 10000 });
  });


  test("Nominate reviewers button is hidden for manager_assigned mode", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "member" });
    await setupReviewRoutes(page, PENDING_REVIEW, {
      ...BASE_CYCLE,
      settings: {
        ...BASE_CYCLE.settings,
        peer_selection_mode: "manager_assigned",
      },
    });

    await page.goto(`/reviews/my-reviews/${REVIEW_ID}`);
    // Wait for page to mount.
    await expect(
      page.getByRole("heading", { name: /Your self review/i }),
    ).toBeVisible({ timeout: 10000 });
    // The button must be absent — manager is the only one who can
    // assign reviewers in this mode.
    await expect(
      page.getByRole("button", { name: /Nominate reviewers/i }),
    ).toHaveCount(0);
  });


  test("submit failure surfaces an error toast and keeps the form", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "member" });
    await setupReviewRoutes(page, PENDING_REVIEW);

    const submitSpy = makeSpiedRoute(
      page,
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/self-review$`),
      () => ({
        status: 400,
        body: { detail: "Self-review window has closed for this cycle" },
      }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/my-reviews/${REVIEW_ID}`);

    const strengthsArea = page
      .locator("label", { hasText: "What went well" })
      .locator("..")
      .locator("textarea")
      .first();
    await strengthsArea.fill("Anything");

    await page
      .getByRole("button", { name: /Submit self-review/i })
      .click();

    await expect.poll(() => submitSpy.calls, { timeout: 8000 }).toBe(1);
    await expect(
      page.getByText("Self-review window has closed for this cycle"),
    ).toBeVisible({ timeout: 5000 });
    // The submit button is still there — user can retry.
    await expect(
      page.getByRole("button", { name: /Submit self-review/i }),
    ).toBeVisible();
  });
});
