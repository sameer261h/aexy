/**
 * E2E: Workflow generation — user types a natural-language description
 * on /automations/new, clicks Generate, and the AI returns a graph
 * that gets rendered into ReactFlow.
 *
 * The endpoint under test is `POST /workspaces/:ws/automations/generate-workflow`.
 * Response contains `{ nodes: [...], edges: [...] }` — we assert at
 * least one node lands in the DOM (`.react-flow__node`).
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

test.describe("AI / Automation workflow generation (live)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
  });

  test("generates a workflow graph from a natural-language prompt", async ({
    page,
  }) => {
    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    // The TemplateGallery (with the generate-from-prompt panel)
    // lives at /automations/new, NOT /automations. The gallery
    // renders by default before a template is picked; canvas only
    // mounts after the user clicks a template or "Start blank".
    await page.goto("/automations/new", {
      waitUntil: "networkidle",
      timeout: 30_000,
    });

    // The textarea uses i18n `automations.generate.describeAriaLabel`
    // which resolves to "Describe the automation" in en. See
    // components/automations/TemplateGallery.tsx:202.
    const promptInput = page.getByRole("textbox", {
      name: /describe the automation/i,
    });
    await expect(promptInput).toBeVisible({ timeout: 15_000 });
    await promptInput.fill(
      "When a CRM contact is created with industry=Healthcare, " +
        "send a welcome email and add a follow-up task.",
    );

    const respPromise = waitForAiResponse(
      page,
      (u) => /\/automations\/generate-workflow(\b|\?|$)/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    await page
      .getByRole("button", { name: /generate workflow|drafting/i })
      .first()
      .click();

    const resp = await respPromise;
    expect(
      resp.status(),
      `generate-workflow returned ${resp.status()}`,
    ).toBeLessThan(500);

    const body = (await resp.json().catch(() => null)) as {
      nodes?: unknown[];
      edges?: unknown[];
    } | null;
    if (body) {
      // The model SHOULD produce at least 1 trigger + 1 action.
      // We're tolerant: just check that the graph isn't trivial.
      expect(Array.isArray(body.nodes)).toBe(true);
      expect((body.nodes ?? []).length).toBeGreaterThan(0);
    }

    // ReactFlow canvas should mount with at least one generated node.
    // Backend now adds `position: {x,y}` to every node (see
    // backend/src/aexy/services/workflow_generator.py::_assign_positions),
    // so the canvas mount should no longer throw.
    await expect(page.locator(".react-flow__node").first()).toBeVisible({
      timeout: 60_000,
    });

    expect(
      errors,
      `fatal API errors during generate-workflow: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
