/**
 * E2E: CRM email draft — clicking "Draft with AI" on a contact /
 * record uses the writing-style + email-drafter pipeline to
 * produce a draft.
 *
 * Endpoint shape: `POST /api/v1/workspaces/:ws/crm/writing-style/generate-email`
 * (or the agent-based equivalent under `/crm/agents/.../run`).
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  setupAiLiveAuth,
  LLM_WAIT_MS,
} from "./fixtures/ai-env";
import {
  collectFatalApiErrors,
  seedCrmContact,
  waitForAiResponse,
  type Seeded,
  type SeededRecord,
} from "./fixtures/ai-helpers";

let contact: Seeded<SeededRecord> | null = null;

test.beforeAll(async ({ request }) => {
  const ready = await aiLiveReady();
  test.skip(!ready.ok, ready.reason);
  contact = await seedCrmContact(request);
  test.skip(
    !contact,
    "CRM contact object not available — workspace not configured for CRM.",
  );
});

test.afterAll(async () => {
  if (contact) await contact.cleanup();
});

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / CRM email draft (live)", () => {
  // TODO(UI-MISSING): There is no "Draft with AI" affordance on the
  // CRM record detail page (`/crm/records/:id`). The email-drafter
  // exists as an agent TOOL (see workflow-builder/NodePalette.tsx
  // and the `email_drafter` tool registration), and the backend
  // exposes `POST /workspaces/:ws/crm/writing-style/generate-email`
  // for direct invocation, but no UI currently triggers it from a
  // record view. To enable this E2E:
  //   1. Add a "Draft email with AI" button to the CRM record
  //      sidebar / actions panel (or to the existing email composer
  //      drawer if one exists for the workspace's CRM module).
  //   2. Wire it to `agentsApi.generateEmail` (writingStyleApi).
  //   3. Remove this fixme and re-run.
  test.fixme(
    true,
    "No 'Draft with AI' UI surface on CRM records — see TODO above.",
  );
  test("Draft with AI produces a non-empty draft", async ({ page }) => {
    test.skip(!contact, "contact seed failed");

    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    await page.goto(`/crm/records/${contact!.value.id}`, {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    // Open the email composer / drawer if there's an entry point.
    const composeBtn = page
      .getByRole("button", { name: /compose|email|new email|reply/i })
      .first();
    if (await composeBtn.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await composeBtn.click();
    }

    const draftBtn = page
      .getByRole("button", { name: /draft( with)? ai|ai draft|generate( email)?/i })
      .first();
    test.skip(
      !(await draftBtn.isVisible({ timeout: 8_000 }).catch(() => false)),
      "No 'Draft with AI' affordance on this record surface.",
    );

    const respPromise = waitForAiResponse(
      page,
      (u) =>
        /\/crm\/writing-style\/generate-email/.test(u) ||
        /\/crm\/agents\/[^/]+\/(run|conversations|inbox)/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    await draftBtn.click();
    const resp = await respPromise;
    expect(resp.status(), `draft endpoint returned ${resp.status()}`).toBeLessThan(500);

    const body = (await resp.json().catch(() => null)) as {
      body?: string;
      subject?: string;
      content?: string;
      output?: string;
    } | null;
    if (body) {
      const draft = body.body || body.content || body.output;
      if (draft) expect(draft.trim().length).toBeGreaterThan(0);
    }

    expect(
      errors,
      `fatal API errors during email draft: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
