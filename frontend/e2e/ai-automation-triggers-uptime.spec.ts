/**
 * E2E: All uptime trigger subtypes — palette → canvas → persistence.
 *
 * Parametrized over every trigger in uptime's registry entry
 * (backend/src/aexy/schemas/automation.py::TRIGGER_REGISTRY["uptime"]).
 * Driven by frontend/e2e/fixtures/automation-schema.generated.json —
 * regenerate with `npm run schema:automation` after adding new triggers
 * on the backend; the `schema:automation:check` CI gate catches drift.
 *
 * Per subtype:
 *   1. Open a fresh canvas filtered to the uptime module
 *   2. Click the subtype from the palette (testid-targeted)
 *   3. Assert the node renders and the config panel opens
 *   4. Save the workflow → fetch via API → assert
 *      `nodes[0].data.trigger_type === <subtype>`
 *   5. Delete the automation in finally{} cleanup
 *
 * Live backend, no LLM (uses backendOnlyReady).
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";
import { collectFatalApiErrors } from "./fixtures/ai-helpers";
import {
  addNodeFromPalette,
  canvasNodes,
  configPanel,
  deleteAutomation,
  fetchWorkflow,
  openCanvas,
  saveWorkflow,
  triggersForModule,
} from "./fixtures/automation-helpers";

const MODULE = "uptime";
const TRIGGERS = triggersForModule(MODULE);

test.describe.configure({ timeout: 90_000 });

test.describe(`AI / Automation triggers (live): ${MODULE}`, () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  if (TRIGGERS.length === 0) {
    test(`[guard] schema fixture has no triggers for ${MODULE}`, () => {
      test.skip(true, `triggersForModule("${MODULE}") returned [] — regenerate fixture`);
    });
  }

  for (const trigger of TRIGGERS) {
    test(`trigger: ${trigger.id}`, async ({ page, request }) => {
      const errors = collectFatalApiErrors(page);
      let automationId: string | null = null;
      try {
        await openCanvas(page, { module: MODULE });
        // Blank canvas ships with a default `trigger-1`. Compare
        // relative counts and identify the persisted node by its
        // subtype (not by "first trigger") so the default doesn't
        // interfere.
        const initialTriggers = await canvasNodes(page, "trigger").count();
        await addNodeFromPalette(page, "trigger", trigger.id);
        await expect(canvasNodes(page, "trigger")).toHaveCount(initialTriggers + 1);
        await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

        automationId = await saveWorkflow(page);
        expect(automationId, "saveWorkflow could not parse automation id").toBeTruthy();

        const persisted = await fetchWorkflow(request, automationId!);
        expect(persisted, "GET /workflow returned non-OK").not.toBeNull();
        const matchingTrigger = (
          persisted!.nodes as Array<{ data?: { trigger_type?: string }; type?: string }>
        ).find((n) => n.type === "trigger" && n.data?.trigger_type === trigger.id);
        expect(
          matchingTrigger,
          `no persisted trigger node with trigger_type === "${trigger.id}"`,
        ).toBeTruthy();

        expect(
          errors,
          `fatal API errors for trigger "${trigger.id}": ${JSON.stringify(errors)}`,
        ).toEqual([]);
      } finally {
        if (automationId) await deleteAutomation(request, automationId);
      }
    });
  }
});
