/**
 * E2E: Workflow templates — every gallery template lands a usable graph.
 *
 * Parametrized over `AUTOMATION_TEMPLATES` in
 * frontend/src/lib/automationTemplates.ts. For each template:
 *
 *   1. Open /automations/new (filtered by template module so the
 *      gallery surfaces the card we want to click).
 *   2. Click the template card (matched by accessible name).
 *   3. Assert the canvas mounts and shows at least one trigger plus
 *      one action node from the template.
 *   4. Assert the persisted trigger_type matches the template's
 *      declared triggerType — proves the template pre-fill flows
 *      through save → API → DB.
 *
 * Templates that include a `run_agent` / `ai_classify` action would
 * need an agent seeded; the current gallery has one such template
 * (ai-triage). For now we run the structural checks against it
 * without invoking the LLM — the canvas should still mount even
 * before the agent picker is wired. If the template later requires a
 * bound agent at save-time, gate that case with `aiLiveReady` + a
 * `seedAgent` block.
 *
 * Live backend, no LLM (uses backendOnlyReady).
 */

import { expect, test } from "@playwright/test";

import { TEMPLATE_LIST } from "../src/lib/automationTemplates";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";
import { collectFatalApiErrors } from "./fixtures/ai-helpers";
import {
  canvasNodes,
  deleteAutomation,
  fetchWorkflow,
  saveWorkflow,
} from "./fixtures/automation-helpers";

test.describe.configure({ timeout: 120_000 });

test.describe("AI / Automation templates (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  if (TEMPLATE_LIST.length === 0) {
    test("[guard] no templates registered in automationTemplates.ts", () => {
      test.skip(true, "TEMPLATE_LIST is empty");
    });
  }

  for (const tmpl of TEMPLATE_LIST) {
    test(`template: ${tmpl.id} (${tmpl.module})`, async ({ page, request }) => {
      const errors = collectFatalApiErrors(page);
      let automationId: string | null = null;
      try {
        // Open the gallery filtered to the template's module so its
        // card sits in the visible bucket.
        await page.goto(`/automations/new?module=${encodeURIComponent(tmpl.module)}`, {
          waitUntil: "networkidle",
          timeout: 30_000,
        });

        // The whole TemplateCard is one `<button onClick={onUse}>` —
        // its accessible name is the concatenation of inner text, so
        // matching by the template name finds the right button. We
        // don't target the heading directly because click bubbling
        // through a heading is fragile when the gallery re-renders.
        const card = page
          .getByRole("button", { name: new RegExp(tmpl.name, "i") })
          .first();
        await expect(
          card,
          `template card for "${tmpl.id}" not visible — name copy may have drifted`,
        ).toBeVisible({ timeout: 15_000 });
        await card.click();

        // After picking a template the canvas mounts with pre-filled
        // nodes from getDefaultNodes(module, template). Give the
        // canvas explicit time to settle — the initial mount can
        // race with the save click otherwise.
        await expect(page.locator(".react-flow").first()).toBeVisible({
          timeout: 15_000,
        });
        await expect(canvasNodes(page, "trigger")).toHaveCount(1);
        expect(
          await canvasNodes(page, "action").count(),
          `expected ≥1 action node for template "${tmpl.id}"`,
        ).toBeGreaterThanOrEqual(1);
        // Allow ReactFlow to fully hydrate its nodes (including their
        // data payload) so the upcoming save serializes them rather
        // than a partial snapshot.
        await page.waitForTimeout(500);

        // Save → fetch → assert the trigger_type round-trips.
        automationId = await saveWorkflow(page);
        expect(
          automationId,
          `saveWorkflow returned no id for template "${tmpl.id}"`,
        ).toBeTruthy();

        const persisted = await fetchWorkflow(request, automationId!);
        expect(persisted, "GET /workflow returned non-OK").not.toBeNull();
        const triggerNode = (
          persisted!.nodes as Array<{ data?: { trigger_type?: string }; type?: string }>
        ).find((n) => n.type === "trigger");
        expect(
          triggerNode?.data?.trigger_type,
          `template "${tmpl.id}" lost its triggerType through save`,
        ).toBe(tmpl.triggerType);

        // The persisted graph should have an action node for every
        // entry in the template's action list (template might add a
        // wait/delay node between them too, so we assert ≥, not =).
        const actionNodes = (persisted!.nodes as Array<{ type?: string }>).filter(
          (n) => n.type === "action",
        );
        expect(
          actionNodes.length,
          `template "${tmpl.id}" persisted ${actionNodes.length} actions, expected ≥${tmpl.actions.length}`,
        ).toBeGreaterThanOrEqual(tmpl.actions.length);

        expect(
          errors,
          `fatal API errors during template "${tmpl.id}": ${JSON.stringify(errors)}`,
        ).toEqual([]);
      } finally {
        if (automationId) await deleteAutomation(request, automationId);
      }
    });
  }
});
