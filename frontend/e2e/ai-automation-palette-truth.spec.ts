/**
 * E2E: palette honesty — the CRM automation palette exposes ONLY what
 * actually executes.
 *
 * Enforces the CRM-only descope (2026-07-15, prds/crm-automations-tracker.md
 * Phase 2):
 *   - Join node removed (engine silently skips it).
 *   - Orphan actions removed (api_request, enrich/classify/generate_summary).
 *   - Non-CRM module triggers/actions descoped (not offered on the CRM palette).
 *   - Core CRM triggers/actions still present.
 *
 * Live backend, no LLM. The palette reads the registry API, which is filtered
 * to ENABLED_MODULES; this spec is the UI-side guard against regressions.
 */

import { expect, test } from "@playwright/test";

import { backendOnlyReady, setupAiLiveAuth } from "./fixtures/ai-env";
import { openCanvas } from "./fixtures/automation-helpers";

test.describe.configure({ timeout: 120_000 });

// Capabilities that MUST NOT appear on the CRM palette after the descope.
const REMOVED_CATEGORIES = ["join"];
const REMOVED_ACTION_SUBTYPES = [
  "api_request",
  "enrich_record",
  "classify_record",
  "generate_summary",
];
// A representative non-CRM trigger that must not leak onto the CRM palette.
const NON_CRM_TRIGGER_SUBTYPES = ["ticket.created", "candidate.created", "campaign.sent"];

// Capabilities that MUST remain.
const CORE_CATEGORIES = ["trigger", "action", "condition", "wait", "agent", "branch"];
const CORE_TRIGGER_SUBTYPES = ["record.created", "field.changed", "stage.changed"];
const CORE_ACTION_SUBTYPES = ["send_email", "create_record", "add_to_list"];

test.describe("AI / Automation palette honesty (live)", () => {
  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
    await openCanvas(page, { module: "crm" });
  });

  test("removed categories are absent", async ({ page }) => {
    for (const kind of REMOVED_CATEGORIES) {
      await expect(
        page.getByTestId(`palette-category-${kind}`),
        `"${kind}" category should be removed from the palette`,
      ).toHaveCount(0);
    }
  });

  test("core categories are present", async ({ page }) => {
    for (const kind of CORE_CATEGORIES) {
      await expect(
        page.getByTestId(`palette-category-${kind}`),
        `"${kind}" category should still be available`,
      ).toBeVisible({ timeout: 10_000 });
    }
  });

  test("orphan actions are removed, core actions remain", async ({ page }) => {
    const category = page.getByTestId("palette-category-action");
    if ((await category.getAttribute("aria-expanded")) === "false") {
      await category.click();
    }
    for (const sub of REMOVED_ACTION_SUBTYPES) {
      await expect(
        page.getByTestId(`palette-subtype-action-${sub}`),
        `action "${sub}" should be removed`,
      ).toHaveCount(0);
    }
    for (const sub of CORE_ACTION_SUBTYPES) {
      await expect(
        page.getByTestId(`palette-subtype-action-${sub}`).first(),
        `action "${sub}" should remain`,
      ).toBeVisible({ timeout: 10_000 });
    }
  });

  test("only CRM triggers are offered", async ({ page }) => {
    const category = page.getByTestId("palette-category-trigger");
    if ((await category.getAttribute("aria-expanded")) === "false") {
      await category.click();
    }
    for (const sub of CORE_TRIGGER_SUBTYPES) {
      await expect(
        page.getByTestId(`palette-subtype-trigger-${sub}`).first(),
        `CRM trigger "${sub}" should be present`,
      ).toBeVisible({ timeout: 10_000 });
    }
    for (const sub of NON_CRM_TRIGGER_SUBTYPES) {
      await expect(
        page.getByTestId(`palette-subtype-trigger-${sub}`),
        `non-CRM trigger "${sub}" should not leak onto the CRM palette`,
      ).toHaveCount(0);
    }
  });
});
