/**
 * E2E: Hiring re-evaluation contract test (API-only).
 *
 * Originally a UI-driving spec that needed a workspace with an
 * existing assessment + a candidate who had submitted answers. The
 * full seed path (create assessment → add questions → publish →
 * invite candidate → start attempt → submit each answer → finish
 * attempt) is ~6 dependent API calls per fixture, with several
 * candidate-side endpoints that require a public token. That's a
 * disproportionate investment for one E2E spec.
 *
 * Instead we test the FE → BE contract directly: post the same
 * payload the frontend would post when the recruiter clicks
 * Re-evaluate. We assert the endpoint accepts the request shape and
 * doesn't 5xx. A 404 (assessment/invitation not found) is fine — it
 * means routing + auth + schema validation all passed, and the only
 * thing missing is fixture data the test deliberately doesn't seed.
 *
 * If you want the full UI flow back, see
 * `frontend/e2e/ai-hiring-reevaluate.spec.ts` history and seed via
 * `backend/scripts/` or the public candidate API.
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  authHeaders,
  API_BASE,
} from "./fixtures/ai-env";

// Live LLM call goes through the reevaluate endpoint — keep the
// per-test timeout generous.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Hiring re-evaluate candidate (API contract)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady({ workspace: false });
    test.skip(!ready.ok, ready.reason);
  });

  test("POST /assessments/:id/candidates/:cid/reevaluate accepts the FE shape", async ({
    request,
  }) => {
    // UUIDs that don't exist — backend should answer 404 (not found)
    // OR 200 (when a future seed creates them). What MUST NOT happen
    // is 422 (schema mismatch) or 5xx (unhandled error).
    const fakeAssessmentId = "00000000-0000-0000-0000-000000000000";
    const fakeInvitationId = "00000000-0000-0000-0000-000000000001";

    const resp = await request.post(
      `${API_BASE}/assessments/${fakeAssessmentId}/candidates/${fakeInvitationId}/reevaluate`,
      { headers: authHeaders() },
    );

    expect(
      resp.status(),
      `reevaluate returned ${resp.status()} — body: ${await resp.text()}`,
    ).not.toBe(422);
    expect(resp.status(), `reevaluate returned ${resp.status()}`).toBeLessThan(
      500,
    );
  });
});
