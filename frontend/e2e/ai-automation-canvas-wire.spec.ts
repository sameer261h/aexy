/**
 * E2E: Canvas wiring — render + save-reload round-trip on a non-trivial graph.
 *
 * The original plan was to build the topology from scratch via mouse-
 * drag connectNodes, but ReactFlow's handle hit-testing is genuinely
 * unreliable under Playwright (~1 of 6 drags lands per attempt; nodes
 * scatter beyond the viewport, source/target handles fall off-screen).
 * Rather than fight that, we exercise the read+save halves of the
 * round-trip:
 *
 *   1. Seed the complex graph via the API (trigger → condition →
 *      [true→action-A, false→action-B] → join → action-final).
 *   2. Navigate to the automation's detail page.
 *   3. Assert the canvas re-hydrates all 6 nodes + 6 edges.
 *   4. Click Save (which fires a PUT with the canvas's current state).
 *   5. Reload — assert the same graph re-renders, proving load/save
 *      are bidirectional.
 *
 * The complement — mouse-drag edge creation — lives in a future
 * `ai-automation-canvas-connect.spec.ts` with retries + viewport
 * fitting; intentionally not blocking this layer on it.
 *
 * Live backend, no LLM.
 */

import { expect, test } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";
import { collectFatalApiErrors } from "./fixtures/ai-helpers";
import {
  canvasEdges,
  canvasNodes,
  deleteAutomation,
  fetchWorkflow,
  saveWorkflow,
} from "./fixtures/automation-helpers";

test.describe.configure({ timeout: 180_000 });

test.describe("AI / Automation canvas wiring (live)", () => {
  let automationId: string | null = null;

  test.beforeEach(async ({ page }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);
  });

  test.afterEach(async ({ request }) => {
    if (automationId) {
      await deleteAutomation(request, automationId);
      automationId = null;
    }
  });

  test(
    "renders a 6-node graph from DB and survives a save→reload",
    async ({ page, request }) => {
      const errors = collectFatalApiErrors(page);

      // Step 1 — seed the automation row.
      const createResp = await request.post(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/automations`,
        {
          headers: authHeaders(),
          data: {
            name: `e2e-canvas-wire-${Date.now()}`,
            description: "Canvas wiring E2E (seeded via API).",
            module: "crm",
            trigger_type: "record.created",
            trigger_config: {},
            actions: [],
          },
        },
      );
      expect(createResp.ok(), `automation create returned ${createResp.status()}`).toBeTruthy();
      const created = await createResp.json();
      automationId = created.id as string;

      // Step 2 — PUT the complex workflow. Shape mirrors what the
      // user would build by hand: a condition splitting to two
      // parallel actions that converge at a join, feeding a final
      // action. Positions match the canvas's auto-layout output so
      // re-saving doesn't shuffle them.
      const nodes = [
        {
          id: "trigger-1",
          type: "trigger",
          position: { x: 80, y: 80 },
          data: { label: "Record Created", trigger_type: "record.created" },
        },
        {
          id: "condition-1",
          type: "condition",
          position: { x: 360, y: 80 },
          data: {
            label: "Has email?",
            conditions: [
              {
                field: "record.values.email",
                operator: "is_not_empty",
                value: "",
              },
            ],
            conjunction: "and",
          },
        },
        {
          id: "action-yes",
          type: "action",
          position: { x: 640, y: 0 },
          data: {
            label: "Send Welcome",
            action_type: "send_email",
            email_subject: "Welcome!",
            email_body: "Hi there — glad to have you.",
          },
        },
        {
          id: "action-no",
          type: "action",
          position: { x: 640, y: 160 },
          data: {
            label: "Notify Owner",
            action_type: "notify_user",
            user_id: "owner",
            message: "New record missing email",
          },
        },
        {
          id: "join-1",
          type: "join",
          position: { x: 920, y: 80 },
          data: { label: "Wait for both", join_type: "all", incoming_branches: 2 },
        },
        {
          id: "action-final",
          type: "action",
          position: { x: 1200, y: 80 },
          data: {
            label: "Create Follow-up Task",
            action_type: "create_task",
            title: "Follow up on new record",
          },
        },
      ];
      const edges = [
        { id: "e1", source: "trigger-1", target: "condition-1" },
        { id: "e2", source: "condition-1", target: "action-yes", sourceHandle: "true" },
        { id: "e3", source: "condition-1", target: "action-no", sourceHandle: "false" },
        { id: "e4", source: "action-yes", target: "join-1" },
        { id: "e5", source: "action-no", target: "join-1" },
        { id: "e6", source: "join-1", target: "action-final" },
      ];

      const putResp = await request.put(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/automations/${automationId}/workflow`,
        {
          headers: authHeaders(),
          data: { nodes, edges, viewport: { x: 0, y: 0, zoom: 1 } },
        },
      );
      expect(
        putResp.ok(),
        `workflow PUT returned ${putResp.status()}: ${await putResp.text()}`,
      ).toBeTruthy();

      // Step 3 — navigate to the detail page. The canvas should
      // re-hydrate the graph.
      await page.goto(`/automations/${automationId}`, {
        waitUntil: "networkidle",
        timeout: 30_000,
      });
      await expect(page.locator(".react-flow").first()).toBeVisible({
        timeout: 15_000,
      });

      // The canvas may render slowly when there are many edges to
      // route — give ReactFlow a moment to settle before counting.
      await expect(canvasNodes(page, "trigger")).toHaveCount(1);
      await expect(canvasNodes(page, "condition")).toHaveCount(1);
      await expect(canvasNodes(page, "action")).toHaveCount(3);
      await expect(canvasNodes(page, "join")).toHaveCount(1);
      await expect(canvasEdges(page)).toHaveCount(6);

      // Step 4 — save and verify the round-trip is symmetric.
      const savedId = await saveWorkflow(page);
      expect(savedId).toBe(automationId);

      const persisted = await fetchWorkflow(request, automationId);
      expect(persisted?.nodes.length).toBe(6);
      expect(persisted?.edges.length).toBe(6);

      // Step 5 — reload and confirm canvas re-renders the same graph.
      await page.reload({ waitUntil: "networkidle" });
      await expect(page.locator(".react-flow").first()).toBeVisible({
        timeout: 15_000,
      });
      await expect(canvasNodes(page, "trigger")).toHaveCount(1);
      await expect(canvasNodes(page, "condition")).toHaveCount(1);
      await expect(canvasNodes(page, "action")).toHaveCount(3);
      await expect(canvasNodes(page, "join")).toHaveCount(1);
      await expect(canvasEdges(page)).toHaveCount(6);

      expect(
        errors,
        `fatal API errors during canvas wiring: ${JSON.stringify(errors)}`,
      ).toEqual([]);
    },
  );
});
