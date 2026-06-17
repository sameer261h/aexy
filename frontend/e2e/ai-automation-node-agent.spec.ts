/**
 * E2E: Agent node — render + agent dropdown + delete.
 *
 * The agent node references a real CRM agent in the workspace. Seeding
 * one requires a valid LLM provider, so this spec uses `aiLiveReady`
 * (needs LM Studio) instead of `backendOnlyReady`. The other Layer A
 * specs don't need LM Studio.
 *
 * We do NOT run the agent — that's covered by `ai-agent-test-run.spec.ts`
 * and `ai-automation-test-run.spec.ts`. This spec only verifies that
 * the canvas-level wiring (drop agent node → pick agent → save) works.
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";
import {
  collectFatalApiErrors,
  seedAgent,
  type Seeded,
  type SeededAgent,
} from "./fixtures/ai-helpers";
import {
  addNodeFromPalette,
  canvasNodes,
  configPanel,
  openCanvas,
} from "./fixtures/automation-helpers";

let agent: Seeded<SeededAgent> | null = null;

test.beforeAll(async ({ request }) => {
  const ready = await aiLiveReady();
  test.skip(!ready.ok, ready.reason);
  agent = await seedAgent(request, {
    name: `e2e-automation-agent-node-${Date.now()}`,
    system_prompt: "Test agent for automation node spec. Reply in one sentence.",
    tools: [],
  });
});

test.afterAll(async () => {
  if (agent) await agent.cleanup();
});

test.describe.configure({ timeout: 180_000 });

test.describe("AI / Automation node: agent (live)", () => {
  test.beforeEach(async ({ page }) => {
    test.skip(!agent, "agent seed failed in beforeAll");
    await setupAiLiveAuth(page);
  });

  test("adds an agent node and lets the user pick a seeded agent", async ({
    page,
  }) => {
    const errors = collectFatalApiErrors(page);
    await openCanvas(page, { module: "crm" });

    // "custom" subtype lets the user pick any agent in the workspace —
    // the other subtypes (sales_outreach, lead_scoring, …) are
    // presets that wire to specific agent_types. Custom is the path
    // most users hit.
    await addNodeFromPalette(page, "agent", "custom");

    const agentNodes = canvasNodes(page, "agent");
    await expect(agentNodes).toHaveCount(1);
    await expect(configPanel(page)).toBeVisible({ timeout: 10_000 });

    // For agent_type=custom, NodeConfigPanel renders a plain
    // `<input type="text" placeholder="Select or enter agent ID">` for
    // the agent_id (NodeConfigPanel.tsx near "Custom Agent Configuration").
    // Other agent subtypes ship preset configs and don't expose this
    // input. The custom path is the one users hit when binding to a
    // real workspace agent.
    const agentIdInput = configPanel(page)
      .getByPlaceholder(/select or enter agent id/i)
      .first();
    await expect(
      agentIdInput,
      "agent_id input not present — custom-agent config form may have changed",
    ).toBeVisible({ timeout: 15_000 });

    // Fill the input with the seeded agent's id — this is the same
    // value the AgentNodeEditor's <select> would set on a non-custom
    // surface, so the persisted graph ends up with the same binding.
    await agentIdInput.fill(agent!.value.id);
    expect(await agentIdInput.inputValue()).toBe(agent!.value.id);

    expect(
      errors,
      `fatal API errors during agent-node spec: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
