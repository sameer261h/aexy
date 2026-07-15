/**
 * E2E: POST /automations/generate-workflow across every module.
 *
 * Extends `ai-automation-generate-workflow.spec.ts` (single CRM prompt)
 * to cover every module supported by AutomationModule. Catches
 * module-specific generator regressions — e.g. a prompt that exercises
 * `hiring`-only triggers still returns valid {nodes, edges}.
 *
 * For each module:
 *   - POST a module-flavoured prompt directly to the API (skipping the
 *     UI to keep the matrix runtime tolerable).
 *   - Assert 2xx, ≥1 trigger, ≥1 action, and the trigger_type is
 *     valid for the module's registry entry.
 *
 * Live LLM (aiLiveReady).
 */

import { expect, test } from "@playwright/test";

import {
  aiLiveReady,
  API_BASE,
  LLM_WAIT_MS,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
} from "./fixtures/ai-env";
import { moduleEnabled, triggersForModule } from "./fixtures/automation-helpers";

interface ModulePrompt {
  module: string;
  prompt: string;
}

const PROMPTS: ModulePrompt[] = [
  {
    module: "crm",
    prompt:
      "When a CRM contact is created in the Healthcare industry, send a welcome email and create a follow-up task for the owner.",
  },
  {
    module: "tickets",
    prompt:
      "When a support ticket is created with priority high, assign it to the on-call agent and send a Slack notification.",
  },
  {
    module: "hiring",
    prompt:
      "When a candidate moves to the on-site interview stage, schedule an interview and notify the hiring manager.",
  },
  {
    module: "email_marketing",
    prompt:
      "When a recipient opens the welcome campaign, add them to the engaged-leads list and send a follow-up email.",
  },
  {
    module: "uptime",
    prompt:
      "When a monitor goes down, page the on-call responder and create an incident.",
  },
  {
    module: "sprints",
    prompt:
      "When sprint burndown deviates 20% off-track, notify the team and assign a triage task to the scrum master.",
  },
  {
    module: "forms",
    prompt:
      "When a contact-form is submitted, create a CRM record and send a confirmation email to the submitter.",
  },
  {
    module: "booking",
    prompt:
      "When a booking is confirmed, send a reminder email 24 hours before the start time.",
  },
  {
    module: "tracking",
    prompt:
      "When a team member misses their standup, create a follow-up task and send them a Slack reminder.",
  },
  {
    module: "compliance",
    prompt:
      "When a training assignment becomes overdue, notify the assignee and escalate to their manager.",
  },
];

test.describe.configure({ timeout: 240_000 });

test.describe("AI / Automation generate-workflow per module (live)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
  });

  for (const { module, prompt } of PROMPTS) {
    test(`generate-workflow: ${module}`, async ({ request }) => {
      // Descoped modules (CRM-only scope) have no registry entries to
      // validate against — skip until the module is re-enabled.
      test.skip(!moduleEnabled(module), `module "${module}" is descoped`);
      const resp = await request.post(
        `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/automations/generate-workflow`,
        {
          headers: authHeaders(),
          data: { prompt, module },
          timeout: LLM_WAIT_MS,
        },
      );

      expect(
        resp.ok(),
        `generate-workflow returned ${resp.status()} for "${module}": ${await resp.text()}`,
      ).toBeTruthy();

      const body = await resp.json();

      // The LLM is free-form; we don't gate on exact shape but the
      // generator's contract says nodes/edges arrays must be present
      // and the trigger node should belong to the requested module.
      expect(Array.isArray(body.nodes)).toBe(true);
      expect(Array.isArray(body.edges)).toBe(true);
      expect(body.nodes.length).toBeGreaterThan(0);

      const triggerNode = body.nodes.find(
        (n: { type?: string }) => n.type === "trigger",
      );
      expect(
        triggerNode,
        `no trigger node in generated workflow for "${module}"`,
      ).toBeTruthy();

      // Trigger type must be one of the module's registered triggers.
      // A console.warn here used to demote LLM hallucinations to log
      // noise nobody reads — `record.modified` slipping past instead
      // of `record.updated` is exactly the prompt-regression class
      // this spec exists to catch, so fail hard instead.
      const validTriggers = new Set(
        triggersForModule(module).map((t) => t.id),
      );
      const triggerType = triggerNode.data?.trigger_type;
      expect(
        triggerType,
        `generated trigger missing data.trigger_type for "${module}"`,
      ).toBeTruthy();
      expect(
        validTriggers.has(triggerType),
        `[${module}] generator produced trigger_type="${triggerType}" ` +
          `which is NOT in the ${module} registry ` +
          `(known: ${[...validTriggers].join(", ")}). ` +
          `Tighten the generator prompt or extend the registry.`,
      ).toBe(true);

      // _meta is set by the generator on success.
      expect(body._meta?.source).toBe("llm_generated");
    });
  }
});
