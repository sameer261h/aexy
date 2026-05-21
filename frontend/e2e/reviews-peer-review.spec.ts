/**
 * E2E: peer-review respond + submit flow.
 *
 * Walks the reviewer's perspective for a peer review request:
 *   1. Pending request → Accept → form opens
 *   2. Pending request → Decline → reason required → confirm
 *   3. Accepted state → submit feedback (strengths + growth + note)
 *   4. Submitted state → "Thanks" screen, no form
 *   5. Not-mine view: read-only message
 *   6. Validation: submit with no content shows a toast, no API call
 *   7. Validation: decline with no reason is blocked
 */

import { test, expect } from "@playwright/test";
import {
  API_BASE,
  DEV,
  setupReviewsMocks,
  makeSpiedRoute,
} from "./fixtures/reviews-mock-data";
import { USE_REAL_BACKEND } from "./fixtures/env";

test.skip(USE_REAL_BACKEND, "mock-only — use reviews-live-smoke.spec.ts in live mode");


const REQUEST_ID = "peer-req-1";
const REVIEW_ID = "review-1";

const PENDING_REQUEST = {
  id: REQUEST_ID,
  review_id: REVIEW_ID,
  requester_id: "requester-1",
  requester_name: "Alice Requester",
  reviewer_id: DEV.id, // belongs to the logged-in user → isMine = true
  reviewer_name: DEV.name,
  status: "pending" as const,
  request_source: "self_nominated",
  message: "Would love your perspective on the auth migration project.",
  decline_reason: null,
  responded_at: null,
  submitted_at: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const ACCEPTED_REQUEST = {
  ...PENDING_REQUEST,
  status: "accepted" as const,
  responded_at: "2026-01-05T00:00:00Z",
};

const COMPLETED_REQUEST = {
  ...PENDING_REQUEST,
  status: "completed" as const,
  responded_at: "2026-01-05T00:00:00Z",
  submitted_at: "2026-01-10T00:00:00Z",
};


test.describe("Reviews / peer review (reviewer perspective)", () => {
  test("Accept transitions pending → feedback form", async ({ page }) => {
    await setupReviewsMocks(page, { role: "member" });

    // Page GETs the request on mount. After accept, it sets local
    // state to the updated request the POST returned.
    await page.route(
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(PENDING_REQUEST),
        }),
    );

    const respondSpy = makeSpiedRoute<{ accept: boolean }>(
      page,
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}/respond$`),
      () => ({ status: 200, body: ACCEPTED_REQUEST }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/peer-requests/${REQUEST_ID}`);

    await expect(
      page.getByRole("button", { name: /^Accept$/ }),
    ).toBeVisible({ timeout: 10000 });
    await page.getByRole("button", { name: /^Accept$/ }).click();

    await expect.poll(() => respondSpy.calls, { timeout: 5000 }).toBe(1);
    expect(respondSpy.lastBody?.accept).toBe(true);

    // After accept, "Write your feedback" heading appears.
    await expect(
      page.getByRole("heading", { name: /Write your feedback/i }),
    ).toBeVisible({ timeout: 5000 });
  });


  test("Decline requires a reason → confirms with the reason", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "member" });

    await page.route(
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(PENDING_REQUEST),
        }),
    );

    const respondSpy = makeSpiedRoute<{
      accept: boolean;
      decline_reason?: string;
    }>(
      page,
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}/respond$`),
      () => ({
        status: 200,
        body: {
          ...PENDING_REQUEST,
          status: "declined",
          decline_reason: "Haven't worked closely with this person this cycle.",
        },
      }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/peer-requests/${REQUEST_ID}`);
    await page.getByRole("button", { name: /^Decline$/ }).click();

    // The decline form appears with a textarea and a "Decline
    // request" button. The button is disabled until a reason is
    // entered.
    const declineBtn = page.getByRole("button", {
      name: /^Decline request$/,
    });
    await expect(declineBtn).toBeVisible({ timeout: 5000 });
    await expect(declineBtn).toBeDisabled();

    await page
      .getByPlaceholder("e.g. I haven't worked closely with this person this cycle.")
      .fill("Haven't worked closely with this person this cycle.");
    await expect(declineBtn).toBeEnabled();
    await declineBtn.click();

    await expect.poll(() => respondSpy.calls, { timeout: 5000 }).toBe(1);
    expect(respondSpy.lastBody?.accept).toBe(false);
    expect(respondSpy.lastBody?.decline_reason).toContain("Haven't worked");
  });


  test("Submit peer feedback POSTs the expected payload", async ({ page }) => {
    await setupReviewsMocks(page, { role: "member" });

    await page.route(
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(ACCEPTED_REQUEST),
        }),
    );

    const submitSpy = makeSpiedRoute<{
      responses: {
        strengths: string[];
        growth_areas: string[];
        // See backend `QuestionResponse` schema: each value is an
        // object with `comment` / `rating`, not a string.
        question_responses: Record<string, { comment?: string; rating?: number }>;
      };
    }>(
      page,
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}/submit`),
      () => ({ status: 201, body: { id: "peer-sub-1" } }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/peer-requests/${REQUEST_ID}`);
    await expect(
      page.getByRole("heading", { name: /Write your feedback/i }),
    ).toBeVisible({ timeout: 10000 });

    await page
      .locator("label", { hasText: "Strengths" })
      .locator("..")
      .locator("textarea")
      .first()
      .fill("Drove the auth migration end-to-end");

    await page
      .locator("label", { hasText: "Growth areas" })
      .locator("..")
      .locator("textarea")
      .first()
      .fill("Could share design rationale earlier");

    await page
      .locator("label", { hasText: "Anything else for context" })
      .locator("..")
      .locator("textarea")
      .first()
      .fill("Great collaborator on hard problems.");

    await page
      .getByRole("button", { name: /Submit peer review/i })
      .click();

    await expect.poll(() => submitSpy.calls, { timeout: 8000 }).toBe(1);
    expect(submitSpy.lastBody?.responses.strengths).toContain(
      "Drove the auth migration end-to-end",
    );
    expect(submitSpy.lastBody?.responses.growth_areas).toContain(
      "Could share design rationale earlier",
    );
    const general = submitSpy.lastBody?.responses.question_responses.general;
    expect(typeof general).toBe("object");
    expect(general?.comment).toContain("Great collaborator");
  });


  test("completed state shows 'Thanks' and hides the form", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "member" });

    await page.route(
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(COMPLETED_REQUEST),
        }),
    );

    await page.goto(`/reviews/peer-requests/${REQUEST_ID}`);
    await expect(
      page.getByText(/Thanks — your feedback has been submitted/i),
    ).toBeVisible({ timeout: 10000 });
    // No write-feedback heading or submit button.
    await expect(
      page.getByRole("heading", { name: /Write your feedback/i }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: /Submit peer review/i }),
    ).toHaveCount(0);
  });


  test("request belonging to another reviewer is read-only", async ({
    page,
  }) => {
    await setupReviewsMocks(page, { role: "member" });

    await page.route(
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...PENDING_REQUEST,
            reviewer_id: "someone-else", // not me
            reviewer_name: "Other Reviewer",
          }),
        }),
    );

    await page.goto(`/reviews/peer-requests/${REQUEST_ID}`);
    await expect(
      page.getByText(/for another reviewer/i),
    ).toBeVisible({ timeout: 10000 });
    // Neither accept nor decline shows up.
    await expect(
      page.getByRole("button", { name: /^Accept$/ }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: /^Decline$/ }),
    ).toHaveCount(0);
  });


  test("empty submit shows a validation toast", async ({ page }) => {
    await setupReviewsMocks(page, { role: "member" });

    await page.route(
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}$`),
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(ACCEPTED_REQUEST),
        }),
    );

    const submitSpy = makeSpiedRoute(
      page,
      new RegExp(`${API_BASE}/reviews/peer-requests/${REQUEST_ID}/submit`),
      () => ({ status: 201, body: {} }),
      (method) => method === "POST",
    );

    await page.goto(`/reviews/peer-requests/${REQUEST_ID}`);
    await expect(
      page.getByRole("button", { name: /Submit peer review/i }),
    ).toBeVisible({ timeout: 10000 });
    await page
      .getByRole("button", { name: /Submit peer review/i })
      .click();

    await expect(
      page.getByText(
        /at least one strength, growth area, or note before submitting/i,
      ),
    ).toBeVisible({ timeout: 3000 });
    expect(submitSpy.calls).toBe(0);
  });
});
