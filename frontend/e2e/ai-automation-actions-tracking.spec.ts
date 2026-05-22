/**
 * E2E: All tracking action subtypes — palette → canvas → persistence.
 *
 * Parametrized over every action available to the tracking module: the
 * common bucket (send_email, send_slack, webhook_call, …) PLUS the
 * tracking-specific bucket (create_record, update_record, enroll_sequence, …).
 * Source: backend/src/aexy/schemas/automation.py::ACTION_REGISTRY.
 * Driven by frontend/e2e/fixtures/automation-schema.generated.json.
 *
 * Per subtype:
 *   1. Open a fresh canvas filtered to the tracking module
 *   2. Click the action subtype from the palette
 *   3. Assert the node renders and the config panel opens
 *   4. Save the workflow → fetch via API → assert
 *      `nodes[i].data.action_type === <subtype>` for the action node
 *   5. Cleanup the automation in finally{}
 *
 * Note: the canvas auto-creates a default trigger row when saving an
 * action-only graph (handleSave uses `defaultTrigger.type` for the
 * automation's `trigger_type` column). We assert the *action* node
 * matches; we don't constrain what the auto-created trigger looks
 * like.
 *
 * Live backend, no LLM (uses backendOnlyReady).
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";
import { collectFatalApiErrors } from "./fixtures/ai-helpers";
import {
  actionsForModule,
  addNodeFromPalette,
  canvasNodes,
  configPanel,
  deleteAutomation,
  fetchWorkflow,
  openCanvas,
  saveWorkflow,
} from "./fixtures/automation-helpers";

const MODULE = "tracking";
const ACTIONS = actionsForModule(MODULE);

test.describe.configure({ timeout: 90_000 });

test.describe(`AI / Automation actions (live): ${MODULE}`, () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  if (ACTIONS.length === 0) {
    test(`[guard] schema fixture has no actions for ${MODULE}`, () => {
      test.skip(true, `actionsForModule("${MODULE}") returned [] — regenerate fixture`);
    });
  }

  for (const action of ACTIONS) {
    test(`action: ${action.id}`, async ({ page, request }) => {
      const errors = collectFatalApiErrors(page);
      let automationId: string | null = null;
      try {
        await openCanvas(page, { module: MODULE });
        await addNodeFromPalette(page, "action", action.id);
        await expect(canvasNodes(page, "action")).toHaveCount(1);
        await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

        automationId = await saveWorkflow(page);
        expect(automationId, "saveWorkflow could not parse automation id").toBeTruthy();

        const persisted = await fetchWorkflow(request, automationId!);
        expect(persisted, "GET /workflow returned non-OK").not.toBeNull();
        const actionNode = (
          persisted!.nodes as Array<{ data?: { action_type?: string }; type?: string }>
        ).find((n) => n.type === "action");
        expect(
          actionNode?.data?.action_type,
          `persisted action_type didn't round-trip for "${action.id}"`,
        ).toBe(action.id);

        expect(
          errors,
          `fatal API errors for action "${action.id}": ${JSON.stringify(errors)}`,
        ).toEqual([]);
      } finally {
        if (automationId) await deleteAutomation(request, automationId);
      }
    });
  }
});
