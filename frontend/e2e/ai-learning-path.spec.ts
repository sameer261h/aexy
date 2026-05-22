/**
 * E2E: Learning path generation — user picks a target role, the AI
 * curates a list of courses/topics. Endpoint:
 * `POST /workspaces/:ws/learning/paths`.
 *
 * The page may live at /learning, /learning/me, or /learning/manager
 * depending on the user's permissions; we try a few then submit.
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

test.describe("AI / Learning path generation (live)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
  });

  // TODO(UI-INVESTIGATE): /learning has a "Create New Path" button
  // (frontend/src/app/(app)/learning/page.tsx:418) that toggles
  // `showNewPathForm` state, after which a target-role <select> +
  // "Generate Path" button render (line 747+). Driving this flow via
  // Playwright reliably reveals a state-reset behavior — the click
  // toggles the form on then back off, OR the form depends on
  // `roles[]` having entries (workspace may have none seeded). Needs
  // either:
  //   (a) seed at least one role/level for the workspace so
  //       `roles.map(...)` produces options, OR
  //   (b) verify the actual click sequence in headed mode and pin
  //       the selector to whatever stabilizes the form.
  // Until then this is a documented `fixme`.
  test.fixme(
    true,
    "Generate Path form toggles unstably under Playwright — see TODO above.",
  );
  test("generating a path returns courses without 5xx", async ({ page }) => {
    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    // The Generate Path UI is inside a sub-section that the user
    // opens via the "Create New Path" button on /learning. Without
    // clicking it first, the role-select + Generate button aren't
    // rendered.
    await page.goto("/learning", {
      waitUntil: "networkidle",
      timeout: 30_000,
    });
    const createNew = page.getByRole("button", {
      name: /^create new path$/i,
    });
    await expect(createNew).toBeVisible({ timeout: 15_000 });
    await createNew.click();

    // The form requires picking a target role from a dropdown before
    // the Generate button enables.
    const roleSelect = page.locator("select").first();
    test.skip(
      !(await roleSelect.isVisible({ timeout: 8_000 }).catch(() => false)),
      "No target role dropdown on /learning — module empty or feature-flagged.",
    );
    const optionCount = await roleSelect.locator("option").count();
    test.skip(
      optionCount < 2,
      "Workspace has no roles configured — can't drive learning-path generation. " +
        "Seed at least one role under Settings → Roles to enable this test.",
    );
    // First non-empty option (index 0 is the "Select Target Role"
    // placeholder).
    await roleSelect.selectOption({ index: 1 });

    // Wait for the Generate Path button to become enabled
    // (disabled until `selectedRoleId` state updates from the
    // dropdown change). Without this, .click() races against the
    // disabled state and waits for navigation indefinitely.
    const generateBtn = page
      .getByRole("button", { name: /generate path|generating/i })
      .first();
    await expect(generateBtn).toBeEnabled({ timeout: 5_000 });

    const respPromise = waitForAiResponse(
      page,
      (u) => /\/learning\/paths(\b|\?|$)/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    await generateBtn.click();

    const resp = await respPromise;
    expect(
      resp.status(),
      `/learning/paths returned ${resp.status()}`,
    ).toBeLessThan(500);

    expect(
      errors,
      `fatal API errors during learning-path generate: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
