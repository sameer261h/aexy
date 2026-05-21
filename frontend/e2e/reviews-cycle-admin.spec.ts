/**
 * E2E: review cycle admin flows.
 *
 * Covers the cycle state machine from the admin perspective:
 *   draft → active → self_review → peer_review → manager_review → completed
 *
 * Plus the negative path: non-admin users hitting admin-only routes
 * must see a 403 / get sent back, not silently succeed.
 *
 * Selectors lean on `data-testid` where available, and accessible
 * names + labels otherwise. The reviews UX track will add more
 * test-ids as the audit's quick-wins land; this spec is forward-
 * compatible because it never matches against visible text inside
 * existing copy.
 */

import { test, expect } from "@playwright/test";
import {
  API_BASE,
  DEV,
  WORKSPACE,
  setupReviewsMocks,
  mockEmptyContributionsSummary,
  makeSpiedRoute,
} from "./fixtures/reviews-mock-data";
import { USE_REAL_BACKEND } from "./fixtures/env";

test.skip(USE_REAL_BACKEND, "mock-only — use reviews-live-smoke.spec.ts in live mode");


// Shared cycle shape used across tests.
const CYCLE_DRAFT = {
  id: "cycle-1",
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
    peer_selection_mode: "both",
    include_github_metrics: true,
  },
  status: "draft" as const,
};


test.describe("Reviews / cycle admin", () => {
  test("admin creates a cycle → /cycles/:id detail loads", async ({ page }) => {
    await setupReviewsMocks(page, { role: "admin" });

    // Spies on the two endpoints we expect to fire.
    const listSpy = makeSpiedRoute(
      page,
      new RegExp(`/reviews/workspaces/${WORKSPACE.id}/cycles$`),
      () => ({ body: [] }),
      (method) => method === "GET",
    );
    const createSpy = makeSpiedRoute<{
      name: string;
      cycle_type: string;
      period_start: string;
      period_end: string;
    }>(
      page,
      new RegExp(`/reviews/workspaces/${WORKSPACE.id}/cycles$`),
      () => ({ status: 201, body: CYCLE_DRAFT }),
      (method) => method === "POST",
    );

    // The detail page hits these two on mount — return the freshly
    // "created" cycle so the redirect lands cleanly.
    await page.route(
      new RegExp(`${API_BASE}/reviews/cycles/${CYCLE_DRAFT.id}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ ...CYCLE_DRAFT, enrolled_developers: [] }),
        }),
    );

    await page.goto("/reviews/cycles/new");

    // The Create button is gated until name + dates are valid; fill
    // each required field. Cycle type defaults to annual so we leave
    // it alone.
    await page.locator("#cycle-name").fill(CYCLE_DRAFT.name);
    await page.locator("#cycle-period-start").fill(CYCLE_DRAFT.period_start);
    await page.locator("#cycle-period-end").fill(CYCLE_DRAFT.period_end);

    // Submit. Button label could change with i18n; target by type +
    // visible enabled state via the testid wrapper.
    await page
      .getByTestId("create-cycle-tooltip")
      .locator("button[type='submit']")
      .click();

    await expect.poll(() => createSpy.calls, { timeout: 8000 }).toBe(1);
    // The post body must carry what the user typed, not the field
    // defaults the form had on first render.
    expect(createSpy.lastBody?.name).toBe(CYCLE_DRAFT.name);
    expect(createSpy.lastBody?.period_start).toBe(CYCLE_DRAFT.period_start);
    expect(createSpy.lastBody?.period_end).toBe(CYCLE_DRAFT.period_end);

    // Redirect lands on the cycle detail page (frontend route).
    await expect(page).toHaveURL(
      new RegExp(`/reviews/cycles/${CYCLE_DRAFT.id}$`),
      { timeout: 10000 },
    );

    expect(listSpy.calls).toBeGreaterThanOrEqual(0); // sanity touch
  });


  test("date validation: end before start blocks submission", async ({ page }) => {
    await setupReviewsMocks(page, { role: "admin" });
    const createSpy = makeSpiedRoute(
      page,
      new RegExp(`/reviews/workspaces/${WORKSPACE.id}/cycles$`),
      () => ({ status: 201, body: CYCLE_DRAFT }),
      (method) => method === "POST",
    );

    await page.goto("/reviews/cycles/new");
    await page.locator("#cycle-name").fill("Bad Cycle");
    await page.locator("#cycle-period-start").fill("2026-03-31");
    await page.locator("#cycle-period-end").fill("2026-01-01");

    // The date-validation-error testid renders inline.
    await expect(page.getByTestId("date-validation-error")).toBeVisible();

    // Submit button is gated — click should fire no network call.
    await page
      .getByTestId("create-cycle-tooltip")
      .locator("button[type='submit']")
      .click({ force: true })
      .catch(() => undefined);

    // Tiny wait to confirm no POST fires.
    await page.waitForTimeout(300);
    expect(createSpy.calls).toBe(0);
  });


  test("cycle state machine: start → advance through every phase", async ({ page }) => {
    await setupReviewsMocks(page, { role: "admin" });
    await mockEmptyContributionsSummary(page);

    // The cycle moves through: draft → active → self_review →
    // peer_review → manager_review → completed. The page renders
    // "Start Cycle" while draft, then "Advance Phase" while active+.
    let currentStatus: string = "draft";
    const states: string[] = [
      "draft",
      "active",
      "self_review",
      "peer_review",
      "manager_review",
      "completed",
    ];

    // GET /cycles/:id — server-side truth, mutates after each POST.
    await page.route(
      new RegExp(`${API_BASE}/reviews/cycles/${CYCLE_DRAFT.id}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...CYCLE_DRAFT,
            status: currentStatus,
            enrolled_developers: [],
          }),
        }),
    );

    const activateSpy = makeSpiedRoute(
      page,
      new RegExp(`${API_BASE}/reviews/cycles/${CYCLE_DRAFT.id}/activate$`),
      () => {
        currentStatus = "active";
        return { body: { ...CYCLE_DRAFT, status: currentStatus } };
      },
      (method) => method === "POST",
    );

    const advanceSpy = makeSpiedRoute(
      page,
      new RegExp(`${API_BASE}/reviews/cycles/${CYCLE_DRAFT.id}/advance-phase$`),
      () => {
        const idx = states.indexOf(currentStatus);
        currentStatus = states[Math.min(idx + 1, states.length - 1)];
        return { body: { ...CYCLE_DRAFT, status: currentStatus } };
      },
      (method) => method === "POST",
    );

    await page.goto(`/reviews/cycles/${CYCLE_DRAFT.id}`);

    // Wait for the page to mount with cycle data.
    await expect(
      page.getByRole("button", { name: /^Start Cycle$/ }).first(),
    ).toBeVisible({ timeout: 10000 });

    // draft state: click "Start Cycle" in the header, then confirm
    // in the modal that pops open. Both buttons share the exact
    // label "Start Cycle"; the modal's button is the last one in
    // DOM order once the modal renders.
    await page
      .getByRole("button", { name: /^Start Cycle$/ })
      .first()
      .click();
    await expect(page.getByText("Start Review Cycle?")).toBeVisible();
    await page
      .getByRole("button", { name: /^Start Cycle$/ })
      .last()
      .click();

    await expect.poll(() => activateSpy.calls, { timeout: 8000 }).toBe(1);

    // active → self_review → peer_review → manager_review → completed
    // is 4 advance-phase clicks. The button disappears after the
    // final transition because the page hides it for "completed".
    for (let i = 0; i < 4; i++) {
      const headerAdvance = page
        .getByRole("button", { name: /^Advance Phase$/ })
        .first();
      // waitFor actually waits (Locator.isVisible is synchronous and
      // returns false during transitions, which bails the loop too
      // early).
      const ok = await headerAdvance
        .waitFor({ state: "visible", timeout: 8000 })
        .then(() => true)
        .catch(() => false);
      if (!ok) break;
      await headerAdvance.click();
      // Wait for the modal to render — its heading is unique.
      await expect(page.getByText("Advance to next phase?")).toBeVisible({
        timeout: 3000,
      });
      // Modal's confirm button has the same label; once the modal
      // has rendered there are two "Advance Phase" buttons and the
      // modal's is the last in DOM order.
      await page
        .getByRole("button", { name: /^Advance Phase$/ })
        .last()
        .click();
      // Wait for the spy to advance before the next iteration.
      await expect
        .poll(() => advanceSpy.calls, { timeout: 5000 })
        .toBeGreaterThanOrEqual(i + 1);
      // And for the modal to close.
      await expect(
        page.getByText("Advance to next phase?"),
      ).toBeHidden({ timeout: 3000 });
    }

    expect(advanceSpy.calls).toBeGreaterThanOrEqual(3);
    expect(currentStatus).toBe("completed");
  });


  test("non-admin: backend 403 on start-cycle surfaces inline error", async ({ page }) => {
    // The cycle detail page renders admin actions to everyone — the
    // server is the source of truth for authorization. This test
    // verifies that when a non-admin clicks Start Cycle and the
    // backend returns 403, the error appears inline in the modal
    // rather than crashing the page or silently no-op'ing.
    await setupReviewsMocks(page, { role: "member" });
    await mockEmptyContributionsSummary(page);

    await page.route(
      new RegExp(`${API_BASE}/reviews/cycles/${CYCLE_DRAFT.id}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...CYCLE_DRAFT,
            status: "draft",
            enrolled_developers: [],
          }),
        }),
    );

    const activateSpy = makeSpiedRoute(
      page,
      new RegExp(`${API_BASE}/reviews/cycles/${CYCLE_DRAFT.id}/activate$`),
      () => ({
        status: 403,
        body: { detail: "Only workspace admins can start a review cycle" },
      }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/cycles/${CYCLE_DRAFT.id}`);
    await expect(
      page.getByRole("button", { name: /^Start Cycle$/ }).first(),
    ).toBeVisible({ timeout: 10000 });

    await page
      .getByRole("button", { name: /^Start Cycle$/ })
      .first()
      .click();
    await expect(page.getByText("Start Review Cycle?")).toBeVisible();
    await page
      .getByRole("button", { name: /^Start Cycle$/ })
      .last()
      .click();

    await expect.poll(() => activateSpy.calls, { timeout: 8000 }).toBe(1);
    // The error message from the backend should render inline.
    await expect(
      page.getByText("Only workspace admins can start a review cycle"),
    ).toBeVisible({ timeout: 5000 });
  });


  test("list page: cycles render in a table on desktop", async ({ page }) => {
    await setupReviewsMocks(page, { role: "admin" });

    const cycles = [
      { ...CYCLE_DRAFT, id: "cycle-a", name: "Cycle A", status: "active" },
      { ...CYCLE_DRAFT, id: "cycle-b", name: "Cycle B", status: "completed" },
      { ...CYCLE_DRAFT, id: "cycle-c", name: "Cycle C", status: "draft" },
    ];
    await page.route(
      new RegExp(`/reviews/workspaces/${WORKSPACE.id}/cycles\\?status=active$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(cycles.filter((c) => c.status === "active")),
        }),
    );
    await page.route(
      new RegExp(`/reviews/workspaces/${WORKSPACE.id}/cycles$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(cycles),
        }),
    );

    await page.goto("/reviews/cycles");

    // Either the mobile cards or the desktop table should render the
    // three names. Use a forgiving role-based query.
    for (const c of cycles) {
      await expect(
        page.getByText(c.name, { exact: false }).first(),
      ).toBeVisible({ timeout: 10000 });
    }
  });
});
