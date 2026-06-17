/**
 * E2E: Workflow containing a `run_agent` action actually fires the
 * agent and the run record carries the LLM output.
 *
 * Distinct from `ai-automation-test-run.spec.ts` (which only verified
 * the execute endpoint doesn't 5xx) — this one verifies the
 * full LLM round-trip: trigger fires → run_agent → workspace agent
 * invokes LM Studio → output lands in the execution's `node_results`.
 *
 * Live LLM required (aiLiveReady). Long timeout — agent loops on a
 * local 9B model can take 60–120s.
 */

import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  aiLiveReady,
  API_BASE,
  LLM_WAIT_MS,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
} from "./fixtures/ai-env";
import {
  collectFatalApiErrors,
  seedAgent,
  type Seeded,
  type SeededAgent,
} from "./fixtures/ai-helpers";
import { deleteAutomation } from "./fixtures/automation-helpers";

let agent: Seeded<SeededAgent> | null = null;

// Distinctive marker we pass IN to the agent via trigger_data and
// expect to find echoed in its output. Asking the agent to repeat a
// data-driven token is far more reliable than instructing it to
// emit a memorised string — a reasoner LLM can spend its reasoning
// budget on the task and drop a hard-coded marker from the final
// response, but it can't drop a token that it's been asked to
// summarise from the payload it just read.
//
// Marker per-test so a stale cached response can't accidentally
// satisfy the assertion in a different run.
const AGENT_MARKER = `PINGACK-RUN-${Date.now()}`;

test.beforeAll(async ({ request }) => {
  const ready = await aiLiveReady();
  test.skip(!ready.ok, ready.reason);
  agent = await seedAgent(request, {
    name: `e2e-runagent-${Date.now()}`,
    // The system prompt enforces a specific output format that
    // can't be satisfied by a passthrough copy of the input: the
    // agent must wrap the echo_token in a literal `[ECHO:...]`
    // envelope. Stub providers / cached responses won't produce
    // that exact shape unless they actually read and shaped the
    // input.
    system_prompt:
      "You are a terse test assistant. Reply with one short sentence " +
      "summarising the trigger payload. The trigger payload includes " +
      "an `echo_token` field — start your reply with the literal " +
      "envelope `[ECHO:<token>]` where <token> is the echo_token " +
      "value, then a space, then your summary. Never use tools.",
    tools: [],
  });
});

test.afterAll(async () => {
  if (agent) await agent.cleanup();
});

test.describe.configure({ timeout: 240_000 });

async function seedAutomationWithRunAgent(
  request: APIRequestContext,
  agentId: string,
): Promise<string> {
  // 1. Create the automation row.
  const create = await request.post(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/automations`,
    {
      headers: authHeaders(),
      data: {
        name: `e2e-run-agent-${Date.now()}`,
        description: "run_agent E2E",
        module: "crm",
        trigger_type: "record.created",
        trigger_config: {},
        actions: [],
      },
    },
  );
  expect(create.ok(), `automation create: ${create.status()}`).toBeTruthy();
  const { id } = await create.json();

  // 2. PUT the workflow: trigger → run_agent.
  const nodes = [
    {
      id: "trigger-1",
      type: "trigger",
      position: { x: 80, y: 80 },
      data: { label: "Record Created", trigger_type: "record.created" },
    },
    {
      id: "agent-1",
      type: "action",
      position: { x: 360, y: 80 },
      data: {
        label: "Run test agent",
        action_type: "run_agent",
        agent_id: agentId,
      },
    },
  ];
  const edges = [{ id: "e1", source: "trigger-1", target: "agent-1" }];
  const put = await request.put(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/automations/${id}/workflow`,
    {
      headers: authHeaders(),
      data: { nodes, edges, viewport: { x: 0, y: 0, zoom: 1 } },
    },
  );
  expect(
    put.ok(),
    `workflow PUT returned ${put.status()}: ${await put.text()}`,
  ).toBeTruthy();

  return id as string;
}

test.describe("AI / Automation run_agent (live)", () => {
  test("workflow execute fires the agent and the run carries LLM output", async ({
    request,
  }) => {
    test.skip(!agent, "agent seed failed");
    const errors: { url: string; status: number }[] = [];
    const automationId = await seedAutomationWithRunAgent(
      request,
      agent!.value.id,
    );

    try {
      // Execute with dry_run=true — unpublished workflows can only
      // run in dry_run per the execute endpoint's contract.
      // `echo_token` is the data-driven marker the agent is told to
      // echo back; finding it in the output proves a real LLM run
      // touched OUR payload (not a cached or stub response).
      const execResp = await request.post(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/automations/${automationId}/workflow/execute`,
        {
          headers: authHeaders(),
          data: {
            dry_run: true,
            trigger_data: {
              echo_token: AGENT_MARKER,
              record: {
                values: {
                  name: "Acme Corp",
                  email: "ops@acme.test",
                  company: "Acme",
                },
              },
            },
          },
          timeout: LLM_WAIT_MS,
        },
      );

      expect(
        execResp.ok(),
        `execute returned ${execResp.status()}: ${await execResp.text()}`,
      ).toBeTruthy();

      const body = await execResp.json();

      // The workflow itself must have completed cleanly. "running" is
      // OK for non-dry-run async paths, but with dry_run=true the
      // execute endpoint is synchronous — anything other than
      // "completed" means the executor bailed and we shouldn't trust
      // any downstream node_results.
      expect(
        body.status,
        `workflow status="${body.status}" error="${body.error}"`,
      ).toBe("completed");
      expect(body.error, "workflow-level error should be null").toBeFalsy();

      const agentResult = (body.node_results ?? []).find(
        (r: { node_id?: string }) => r.node_id === "agent-1",
      );
      expect(
        agentResult,
        `expected node_results entry for agent-1, got: ${JSON.stringify(
          body.node_results,
          null,
          2,
        )}`,
      ).toBeTruthy();

      // Node-level health. A `failed` status with an error message
      // like "Connection error." would have satisfied the old
      // "output is truthy" assertion — that's the false-positive
      // class this whole block exists to prevent.
      expect(
        agentResult.status,
        `agent node status="${agentResult.status}" error="${agentResult.error}"`,
      ).not.toBe("failed");
      expect(
        agentResult.error,
        `agent node carried an error: ${agentResult.error}`,
      ).toBeFalsy();

      // Marker check: the system prompt told the agent to wrap the
      // echo_token (passed via trigger_data below) in a literal
      // `[ECHO:<token>]` envelope. The envelope shape can't appear
      // by accident:
      //   - Stub providers don't produce structured prefixes.
      //   - Cached responses for a different prompt wouldn't carry
      //     this specific token (it's per-test, timestamp-based).
      //   - A passthrough of input data wouldn't add the brackets.
      //
      // We search output + output_data for the exact envelope.
      const envelope = `[ECHO:${AGENT_MARKER}]`;
      const haystack = JSON.stringify({
        output: agentResult.output,
        output_data: agentResult.output_data,
      });
      expect(
        haystack.includes(envelope),
        `agent output did not contain envelope "${envelope}". ` +
          `node_result was: ${JSON.stringify(agentResult, null, 2).slice(0, 1500)}`,
      ).toBe(true);
    } finally {
      await deleteAutomation(request, automationId);
    }

    expect(
      errors,
      `fatal API errors during run_agent execute: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
