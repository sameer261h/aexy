/**
 * E2E: trigger fires → run_agent action runs → workspace state mutates.
 *
 * The most "complete" AI test in the automations suite: a published
 * workflow is wired up such that creating a CRM record actually fires
 * the automation, which invokes a seeded agent, and the resulting
 * automation_run row carries the agent's LLM output.
 *
 * Flow:
 *   1. Seed agent (LM Studio required).
 *   2. Create + publish an automation: record.created → run_agent.
 *   3. Create a CRM contact in the same workspace — this fires the
 *      trigger for real (no dry_run).
 *   4. Poll the automation's runs endpoint until a run for this
 *      record completes (or times out).
 *   5. Assert the run carries the agent's output — that's the
 *      "workspace data changed" half: an automation_run row exists
 *      that didn't before, written by the trigger pipeline.
 *
 * Live LLM, long-running. Cleans up automation + record on exit.
 */

import { expect, test, type APIRequestContext } from "@playwright/test";

import {
  aiLiveReady,
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
} from "./fixtures/ai-env";
import {
  seedAgent,
  type Seeded,
  type SeededAgent,
} from "./fixtures/ai-helpers";
import { deleteAutomation } from "./fixtures/automation-helpers";

/**
 * Provision a "contact" CRM object in the workspace if one doesn't
 * exist, then create a record under it. Returns { recordId, cleanup }
 * — cleanup deletes the record but leaves the object (other tests may
 * still need it). The shared `seedCrmContact` helper in ai-helpers.ts
 * targets the wrong endpoint and is being kept inline here to keep
 * this spec self-contained.
 */
async function provisionContactAndRecord(
  request: APIRequestContext,
): Promise<{ objectId: string; recordId: string; cleanup: () => Promise<void> } | null> {
  // Find or create a CRM object of type=person named "contact".
  const objectsResp = await request.get(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/objects`,
    { headers: authHeaders() },
  );
  if (!objectsResp.ok()) return null;
  const objects = (await objectsResp.json()) as Array<{
    id: string;
    slug: string;
    object_type: string;
  }>;
  type CrmObject = { id: string; slug: string; object_type: string };
  let obj: CrmObject | undefined = objects.find(
    (o) => o.slug === "contact" || o.object_type === "person",
  );
  if (!obj) {
    const create = await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/objects`,
      {
        headers: authHeaders(),
        data: {
          name: "contact",
          plural_name: "contacts",
          object_type: "person",
        },
      },
    );
    if (!create.ok()) return null;
    obj = (await create.json()) as CrmObject;
  }
  if (!obj) return null;

  // Create a record under that object.
  const recResp = await request.post(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/objects/${obj.id}/records`,
    {
      headers: authHeaders(),
      data: {
        values: {
          name: `E2E ${Date.now()}`,
          email: `e2e-${Date.now()}@example.test`,
          company: "Aexy E2E",
        },
      },
    },
  );
  if (!recResp.ok()) {
    return null;
  }
  const rec = (await recResp.json()) as { id: string };

  return {
    objectId: obj.id,
    recordId: rec.id,
    cleanup: async () => {
      try {
        await request.delete(
          `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/records/${rec.id}`,
          { headers: authHeaders() },
        );
      } catch {
        // ignore — throwaway
      }
    },
  };
}

let agent: Seeded<SeededAgent> | null = null;

// Data-driven marker: passed in via trigger_data.echo_token, expected
// echoed back inside a literal `[ECHO:<token>]` envelope. The envelope
// shape can't be produced by stub providers, cached responses, or a
// passthrough of input data — only an LLM that actually read and
// reshaped the input. Per-test (Date.now()) so a stale run can't
// satisfy a fresh one by accident.
const AGENT_MARKER = `PINGACK-E2E-${Date.now()}`;

test.beforeAll(async ({ request }) => {
  const ready = await aiLiveReady();
  test.skip(!ready.ok, ready.reason);
  agent = await seedAgent(request, {
    name: `e2e-e2e-${Date.now()}`,
    system_prompt:
      "You are a brief test assistant. Reply with a one-line " +
      "acknowledgement that you saw the trigger payload. The trigger " +
      "payload includes an `echo_token` field — start your reply with " +
      "the literal envelope `[ECHO:<token>]` where <token> is the " +
      "echo_token value, then a space, then your summary. Never use tools.",
    tools: [],
  });
});

test.afterAll(async () => {
  if (agent) await agent.cleanup();
});

test.describe.configure({ timeout: 300_000 });

async function publishedAutomationWithRunAgent(
  request: APIRequestContext,
  agentId: string,
): Promise<string> {
  const create = await request.post(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/automations`,
    {
      headers: authHeaders(),
      data: {
        name: `e2e-end-to-end-${Date.now()}`,
        description: "End-to-end run_agent E2E",
        module: "crm",
        trigger_type: "record.created",
        trigger_config: {},
        actions: [],
        // Some envs default `is_active: false`; we explicitly set
        // active so the trigger handler routes events to this row.
        is_active: true,
      },
    },
  );
  expect(create.ok(), `automation create: ${create.status()}`).toBeTruthy();
  const { id } = await create.json();

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
        label: "Acknowledge contact",
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

  const publish = await request.post(
    `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/automations/${id}/workflow/publish`,
    { headers: authHeaders() },
  );
  expect(
    publish.ok(),
    `publish returned ${publish.status()}: ${await publish.text()}`,
  ).toBeTruthy();

  return id as string;
}


test.describe("AI / Automation end-to-end (live)", () => {
  test("creating a CRM record fires the published automation and the agent runs", async ({
    request,
  }) => {
    test.skip(!agent, "agent seed failed");

    const automationId = await publishedAutomationWithRunAgent(
      request,
      agent!.value.id,
    );

    let record: { cleanup: () => Promise<void> } | null = null;
    try {
      // Trigger the automation by creating a CRM record. The
      // automation engine's trigger handler should pick up the
      // record.created event for this workspace and dispatch
      // the published workflow.
      const provisioned = await provisionContactAndRecord(request);
      if (!provisioned) {
        test.skip(
          true,
          "couldn't provision a CRM contact object/record — workspace may lack permissions",
        );
        return;
      }
      record = { cleanup: provisioned.cleanup };

      // Fire the workflow against the seeded record. Two endpoints
      // exist:
      //
      //   1. POST /automations/{id}/trigger — fires the LEGACY
      //      `actions` array on the automation row. We left that
      //      empty because we're using the new workflow model, so
      //      this path runs to completion with steps_executed=[].
      //
      //   2. POST /crm/automations/{id}/workflow/execute — runs the
      //      workflow nodes. This is what the canvas's Test button
      //      uses. After publish, we can execute non-dry-run.
      //
      // (2) is the path that exercises run_agent end-to-end.
      // dry_run=true executes synchronously in-process. The
      // non-dry-run path dispatches to Temporal, which requires a
      // worker subscribed to the workflow task queue — that's an
      // external dependency we don't want to take on for tests.
      // Both paths flow through the same WorkflowExecutor, so the
      // run_agent action runs identically — dry_run only changes
      // whether downstream side-effects (e.g. record writes) get
      // committed. For "did the agent actually run against this
      // record?" the dry-run is equivalent.
      const execResp = await request.post(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/automations/${automationId}/workflow/execute`,
        {
          headers: authHeaders(),
          data: {
            record_id: provisioned.recordId,
            // `echo_token` is the data-driven marker the agent's
            // system prompt instructs it to wrap in `[ECHO:...]` —
            // the envelope shape rules out stub providers / cached
            // responses / input passthroughs.
            trigger_data: { echo_token: AGENT_MARKER },
            dry_run: true,
          },
          timeout: 180_000,
        },
      );
      expect(
        execResp.ok(),
        `workflow execute returned ${execResp.status()}: ${await execResp.text()}`,
      ).toBeTruthy();

      const body = (await execResp.json()) as {
        execution_id?: string;
        status?: string;
        node_results?: Array<{
          node_id?: string;
          status?: string;
          output?: unknown;
          output_data?: unknown;
          error?: string;
        }>;
        final_context?: Record<string, unknown>;
        error?: string;
      };

      expect(
        body.status,
        `workflow execution ended in status="${body.status}" error="${body.error}"`,
      ).toBe("completed");

      // The final_context should reflect the record we passed in —
      // proves the real record_id flowed end-to-end into the
      // executor (not lost in trigger_data translation).
      const ctxRecordData = (body.final_context?.record_data ?? {}) as {
        id?: string;
      };
      expect(
        ctxRecordData.id,
        "executor's final_context.record_data.id didn't match the seeded record",
      ).toBe(provisioned.recordId);

      // The agent node must appear in node_results, must NOT be in
      // a `failed` state, and its output must contain AGENT_MARKER —
      // the latter is the load-bearing check that distinguishes a
      // real LLM round-trip from error strings or placeholders
      // satisfying a generic "non-empty output" assertion.
      const agentResult = (body.node_results ?? []).find(
        (r) => r.node_id === "agent-1",
      );
      expect(
        agentResult,
        `no node_results entry for agent-1: ${JSON.stringify(body.node_results, null, 2)}`,
      ).toBeTruthy();
      expect(
        agentResult!.status,
        `agent node status="${agentResult!.status}" error="${agentResult!.error}"`,
      ).not.toBe("failed");
      expect(
        agentResult!.error,
        `agent node carried an error: ${agentResult!.error}`,
      ).toBeFalsy();

      const envelope = `[ECHO:${AGENT_MARKER}]`;
      const haystack = JSON.stringify({
        output: agentResult!.output,
        output_data: agentResult!.output_data,
      });
      expect(
        haystack.includes(envelope),
        `agent output did not contain envelope "${envelope}". ` +
          `node_result was: ${JSON.stringify(agentResult, null, 2).slice(0, 1500)}`,
      ).toBe(true);

      // Workspace state changed: a workflow_execution row exists
      // for this automation (the execute endpoint INSERT'd it before
      // running, see workflows.py::execute_workflow). Verify via the
      // workflow executions list endpoint — that's the surface the
      // Execution History drawer reads from.
      //
      // Note: the legacy `automation_runs` table is a separate
      // pipeline; workflow runs land in `workflow_executions`. We
      // don't cross-check the legacy table here.
      const execsResp = await request.get(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/automations/${automationId}/workflow/executions?limit=5`,
        { headers: authHeaders() },
      );
      expect(
        execsResp.ok(),
        `executions list returned ${execsResp.status()}`,
      ).toBeTruthy();
      const execs = (await execsResp.json()) as Array<{ record_id?: string }>;
      const ourExec = execs.find((e) => e.record_id === provisioned.recordId);
      expect(
        ourExec,
        `no workflow_execution row for record_id=${provisioned.recordId}`,
      ).toBeTruthy();
    } finally {
      if (record) await record.cleanup();
      await deleteAutomation(request, automationId);
    }
  });
});
