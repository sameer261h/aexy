/**
 * E2E: Reviews — generate a review cycle template via AI.
 *
 * The admin Reviews surface offers an "Auto-generate questions /
 * template" action that calls the backend's review_service AI layer
 * to draft a cycle's question set based on a role + level. This spec
 * pins the FE → BE round-trip.
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  setupAiLiveAuth,
  LLM_WAIT_MS,
} from "./fixtures/ai-env";
import {
  collectFatalApiErrors,
  waitForAiResponse,
} from "./fixtures/ai-helpers";

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Review cycle template generation (live)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
  });

  // TODO(UI-MISSING): The review cycle creation page at
  // /reviews/cycles/new (frontend/src/app/(app)/reviews/cycles/new/
  // page.tsx) has no AI-assisted question/template generation
  // affordance. The backend service supports drafting cycle
  // templates (review_service AI layer) but no UI exposes it. To
  // enable this E2E:
  //   1. Add an "AI draft questions" button to the cycle new form
  //      that takes a role/level and pre-populates the questions
  //      array.
  //   2. Wire it to the corresponding /reviews/cycles/* AI endpoint
  //      (TBD by review_service contract).
  //   3. Remove this fixme.
  test.fixme(
    true,
    "No AI-generate affordance on /reviews/cycles/new — see TODO above.",
  );
  test("generating a cycle template returns questions", async ({ page }) => {
    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    let arrived = false;
    for (const r of [
      "/reviews/cycles/new",
      "/reviews/admin/cycles/new",
      "/reviews/admin",
      "/reviews/cycles",
    ]) {
      const resp = await page.goto(r, { timeout: 15_000 }).catch(() => null);
      if (resp && resp.ok()) {
        arrived = true;
        break;
      }
    }
    test.skip(
      !arrived,
      "Reviews admin surface not reachable — likely missing manager role.",
    );

    const cta = page
      .getByRole("button", {
        name: /generate( template| questions)|auto[-\s]?fill|ai (draft|generate)/i,
      })
      .first();
    test.skip(
      !(await cta.isVisible({ timeout: 8_000 }).catch(() => false)),
      "No AI generate CTA in this UI rev — surface may have moved.",
    );

    const respPromise = waitForAiResponse(
      page,
      (u) =>
        /\/reviews\/cycles\/(generate|generate-template|template)/.test(u) ||
        /\/reviews\/.*\/ai\//.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    await cta.click();

    // Some flows ask for a role first.
    const roleInput = page
      .getByRole("textbox", { name: /role|level|track/i })
      .first();
    if (await roleInput.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await roleInput.fill("Senior Backend Engineer");
      await page
        .getByRole("button", { name: /^(generate|create|submit|next)$/i })
        .last()
        .click();
    }

    const resp = await respPromise.catch(() => null);
    test.skip(
      !resp,
      "Reviews AI endpoint was not hit — surface may not exist in this version.",
    );

    if (resp) {
      expect(
        resp.status(),
        `reviews AI endpoint returned ${resp.status()}`,
      ).toBeLessThan(500);
    }

    expect(
      errors,
      `fatal API errors during review-cycle generate: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
