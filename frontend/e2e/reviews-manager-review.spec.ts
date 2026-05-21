/**
 * E2E: manager-review surface.
 *
 * The /reviews/manage/:reviewId page is mostly a read-only
 * dashboard — quick stats, tabs (overview/goals/contributions/
 * feedback), and the "Invite Peer Reviewers" modal which fires
 * `assignPeerReviewers` in `manager_assign` mode.
 *
 * Tests:
 *   1. Loads the review detail with header + member name
 *   2. Tab switcher toggles content (overview / goals / contributions / feedback)
 *   3. Empty feedback tab renders "No peer reviews received yet"
 *   4. Invite Peer Reviewers button opens the modal
 *   5. Modal lists workspace members (filtered, reviewee excluded)
 *   6. Selecting >= min reviewers + Assign fires assignPeerReviewers
 *   7. Backend 403 surfaces an error toast
 *   8. Self-as-reviewee is excluded from the picker
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

test.skip(USE_REAL_BACKEND, "mock-only — use reviews-live-smoke.spec.ts in live mode");


const REVIEW_ID = "review-1";
const CYCLE_ID = "cycle-1";
const REVIEWEE_ID = "reviewee-1";

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
    peer_selection_mode: "manager_assigned" as const,
    include_github_metrics: true,
  },
  status: "peer_review" as const,
  enrolled_developers: [],
};

const REVIEW = {
  id: REVIEW_ID,
  review_cycle_id: CYCLE_ID,
  developer_id: REVIEWEE_ID,
  developer_name: "Sam Reviewee",
  developer_email: "sam@example.com",
  manager_id: DEV.id, // logged-in user is the manager
  manager_name: DEV.name,
  status: "pending" as const,
  self_review: null,
  manager_review: null,
  overall_rating: null,
  ratings_breakdown: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const WORKSPACE_MEMBERS = [
  {
    id: "mem-1",
    developer_id: REVIEWEE_ID,
    developer_name: "Sam Reviewee",
    developer_email: "sam@example.com",
    role: "member",
    is_active: true,
  },
  {
    id: "mem-2",
    developer_id: "peer-a",
    developer_name: "Alice Peer",
    developer_email: "alice@example.com",
    role: "member",
    is_active: true,
  },
  {
    id: "mem-3",
    developer_id: "peer-b",
    developer_name: "Bob Peer",
    developer_email: "bob@example.com",
    role: "member",
    is_active: true,
  },
  {
    id: "mem-4",
    developer_id: "peer-c",
    developer_name: "Carol Peer",
    developer_email: "carol@example.com",
    role: "member",
    is_active: true,
  },
];


// Wires up the routes every manager-review test needs:
//   - GET /reviews/:id          → REVIEW
//   - GET /reviews/cycles/:id   → BASE_CYCLE
//   - GET goal-suggestions      → []
//   - GET workspace members     → WORKSPACE_MEMBERS
//   - GET peer-requests-for-review → []  (no existing invites)
//   - GET workspace goals       → []   (manage page reads goals for the member)
async function setupManagerRoutes(page: import("@playwright/test").Page) {
  await page.route(
    new RegExp(`${API_BASE}/reviews/${REVIEW_ID}$`),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(REVIEW),
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
  // Goal suggestions endpoint shape: array. Empty.
  await page.route(/.*\/reviews\/developers\/.+\/goal-suggestions.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "[]",
    }),
  );
  // Workspace members.
  await page.route(
    new RegExp(`/workspaces/${WORKSPACE.id}/members`),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(WORKSPACE_MEMBERS),
      }),
  );
}


test.describe("Reviews / manager review", () => {
  test("loads the review detail with reviewee name + cycle context", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "admin" });
    await setupManagerRoutes(page);

    await page.goto(`/reviews/manage/${REVIEW_ID}`);

    await expect(
      page.getByText("Sam Reviewee", { exact: false }).first(),
    ).toBeVisible({ timeout: 10000 });
  });


  test("tab switcher renders feedback tab content", async ({ page }) => {
    await setupReviewsMocks(page, { role: "admin" });
    await setupManagerRoutes(page);

    await page.goto(`/reviews/manage/${REVIEW_ID}`);
    await expect(page.getByTestId("tab-feedback")).toBeVisible({
      timeout: 10000,
    });
    await page.getByTestId("tab-feedback").click();

    // With no peer reviews yet, the empty-state copy shows.
    await expect(
      page.getByText(/No peer reviews received yet/i),
    ).toBeVisible({ timeout: 5000 });
  });


  test("'Invite Peer Reviewers' opens the modal with member list", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "admin" });
    await setupManagerRoutes(page);

    await page.goto(`/reviews/manage/${REVIEW_ID}`);

    await page
      .getByRole("button", { name: /Invite Peer Reviewers/i })
      .click();

    // Modal heading.
    await expect(
      page.getByRole("heading", { name: /Invite peer reviewers/i }),
    ).toBeVisible({ timeout: 5000 });

    // Reviewee is excluded — Sam shouldn't appear in the modal's
    // member list. The other three peers should.
    await expect(page.getByText("Alice Peer")).toBeVisible();
    await expect(page.getByText("Bob Peer")).toBeVisible();
    await expect(page.getByText("Carol Peer")).toBeVisible();
    // Sam Reviewee is the page header AND the reviewee — within the
    // modal scope alone, they should NOT be selectable.
    const modal = page.getByRole("heading", { name: /Invite peer reviewers/i }).locator("..").locator("..");
    await expect(modal.getByText("Sam Reviewee")).toHaveCount(0);
  });


  test("assign two peers → POST /assign-peer-reviewers fires once", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "admin" });
    await setupManagerRoutes(page);

    const assignSpy = makeSpiedRoute<{
      reviewer_ids: string[];
      message?: string;
    }>(
      page,
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/assign-peer-reviewers`),
      () => ({
        status: 200,
        body: [
          { id: "req-a", reviewer_id: "peer-a", status: "pending" },
          { id: "req-b", reviewer_id: "peer-b", status: "pending" },
        ],
      }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/manage/${REVIEW_ID}`);
    await page
      .getByRole("button", { name: /Invite Peer Reviewers/i })
      .click();
    await expect(
      page.getByRole("heading", { name: /Invite peer reviewers/i }),
    ).toBeVisible({ timeout: 5000 });

    // Click Alice and Bob. Each row has the name as its visible
    // text — clicking the row toggles selection.
    await page.getByText("Alice Peer").click();
    await page.getByText("Bob Peer").click();

    // The CTA in `manager_assign` mode is labelled
    // "Assign reviewers". Match by the button role.
    const submit = page.getByRole("button", { name: /Invite\s*\d*\s*reviewers?/i });
    await expect(submit).toBeEnabled();
    await submit.click();

    await expect.poll(() => assignSpy.calls, { timeout: 5000 }).toBe(1);
    expect(assignSpy.lastBody?.reviewer_ids).toEqual(
      expect.arrayContaining(["peer-a", "peer-b"]),
    );
    expect(assignSpy.lastBody?.reviewer_ids).toHaveLength(2);
  });


  test("min-reviewer guard: clicking Assign with too few selected stays open", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "admin" });
    await setupManagerRoutes(page);

    const assignSpy = makeSpiedRoute(
      page,
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/assign-peer-reviewers`),
      () => ({ status: 200, body: [] }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/manage/${REVIEW_ID}`);
    await page
      .getByRole("button", { name: /Invite Peer Reviewers/i })
      .click();

    // Cycle min is 2; only select one.
    await page.getByText("Alice Peer").click();
    await page.getByRole("button", { name: /Invite\s*\d*\s*reviewers?/i }).click();

    // Toast surfaces the floor — and the POST never fires.
    await expect(
      page.getByText(/Pick at least 2 reviewers/i),
    ).toBeVisible({ timeout: 3000 });
    expect(assignSpy.calls).toBe(0);
  });


  test("backend 403 on assign surfaces an error toast", async ({ page }) => {
    await setupReviewsMocks(page, { role: "admin" });
    await setupManagerRoutes(page);

    const assignSpy = makeSpiedRoute(
      page,
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/assign-peer-reviewers`),
      () => ({
        status: 403,
        body: { detail: "Only the assigned manager can invite peer reviewers" },
      }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/manage/${REVIEW_ID}`);
    await page
      .getByRole("button", { name: /Invite Peer Reviewers/i })
      .click();
    await page.getByText("Alice Peer").click();
    await page.getByText("Bob Peer").click();
    await page.getByRole("button", { name: /Invite\s*\d*\s*reviewers?/i }).click();

    await expect.poll(() => assignSpy.calls, { timeout: 5000 }).toBe(1);
    await expect(
      page.getByText("Only the assigned manager can invite peer reviewers"),
    ).toBeVisible({ timeout: 5000 });
  });


  test("existing-invite reviewer can't be re-selected", async ({ page }) => {
    await setupReviewsMocks(page, { role: "admin" });
    await setupManagerRoutes(page);
    // Override AFTER setupManagerRoutes so the last-registered route
    // wins for peer-requests — Alice already has a pending invite.
    await page.unroute(
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/peer-requests$`),
    );
    await page.route(
      new RegExp(`${API_BASE}/reviews/${REVIEW_ID}/peer-requests$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([
            {
              id: "existing-req",
              reviewer_id: "peer-a",
              reviewer_name: "Alice Peer",
              status: "pending",
              request_source: "manager",
              created_at: "2026-01-02T00:00:00Z",
              updated_at: "2026-01-02T00:00:00Z",
            },
          ]),
        }),
    );

    await page.goto(`/reviews/manage/${REVIEW_ID}`);
    await page
      .getByRole("button", { name: /Invite Peer Reviewers/i })
      .click();
    await expect(
      page.getByRole("heading", { name: /Invite peer reviewers/i }),
    ).toBeVisible({ timeout: 5000 });

    // Clicking Alice should fire a toast and leave selection empty.
    await page.getByText("Alice Peer").click();
    await expect(
      page.getByText(/Already.*can't re-invite/i),
    ).toBeVisible({ timeout: 3000 });
  });
});
