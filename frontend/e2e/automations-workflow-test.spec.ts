/**
 * E2E smoke test for the workflow Test button on /automations/new.
 *
 * Pins the fix from commit 84b091ae: clicking Test → Generate →
 * Run Test on a never-saved automation must auto-create the
 * automation row + persist the workflow + fire the test endpoint.
 *
 * Pre-fix behavior: the test path bailed silently because the
 * page-level handleTest returned when automationId was null. No
 * spinner, no toast, no network call.
 *
 * Post-fix behavior: canvas-level handleTest auto-saves first
 * (which lazy-creates the automation), then fires the test.
 */

import { test, expect, Page } from "@playwright/test";

const API_BASE = "http://localhost:8000/api/v1";

// Mirror enough of the billing-mock fixture to bootstrap the app
// without pulling in its plan-specific routing. The workflow surface
// only needs auth + workspace + a few empty list endpoints.
async function setupAutomationsMocks(page: Page) {
  // Auth + workspace boot — must run BEFORE the app reads localStorage.
  await page.addInitScript(() => {
    localStorage.setItem("token", "fake-test-token");
    localStorage.setItem("current_workspace_id", "ws-1");
  });

  // Catch-all returns empty array first so list hooks (notifications,
  // search, etc) don't blow up with "x.find is not a function".
  // Playwright matches routes in REVERSE registration order so this
  // must come FIRST.
  await page.route(`${API_BASE}/**`, (route) => {
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  // Some hooks expect object-shaped responses, not arrays. Override
  // the catch-all for those. Each shape is "smallest that the hook
  // accepts without throwing" — we don't care about the actual data,
  // only that the canvas mounts.
  await page.route(`${API_BASE}/notifications**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ notifications: [], unread_count: 0 }),
    }),
  );

  // App-access lookup. Endpoint is
  // /workspaces/:ws/app-access/members/:developerId/effective — match
  // it loosely so we don't pin the developer id.
  await page.route(/\/app-access\/members\/.+\/effective.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        apps: {
          // Enable every app the shell might check so the canvas
          // route isn't gated. We're not testing app-access here.
          agents: { enabled: true, role: "admin" },
          automations: { enabled: true, role: "admin" },
          dashboard: { enabled: true, role: "admin" },
          crm: { enabled: true, role: "admin" },
          docs: { enabled: true, role: "admin" },
          tickets: { enabled: true, role: "admin" },
          email_marketing: { enabled: true, role: "admin" },
          hiring: { enabled: true, role: "admin" },
          sprints: { enabled: true, role: "admin" },
          forms: { enabled: true, role: "admin" },
          tables: { enabled: true, role: "admin" },
          uptime: { enabled: true, role: "admin" },
          tracking: { enabled: true, role: "admin" },
          compliance: { enabled: true, role: "admin" },
          gtm: { enabled: true, role: "admin" },
          analytics: { enabled: true, role: "admin" },
          insights: { enabled: true, role: "admin" },
          reports: { enabled: true, role: "admin" },
          reviews: { enabled: true, role: "admin" },
          learning: { enabled: true, role: "admin" },
          booking: { enabled: true, role: "admin" },
          onboarding: { enabled: true, role: "admin" },
          notifications: { enabled: true, role: "admin" },
        },
        applied_template_id: null,
        applied_template_name: null,
        has_custom_overrides: false,
        is_admin: true,
      }),
    }),
  );

  // Workspace members + spaces — present but empty.
  await page.route(/.*\/workspaces\/ws-1\/members.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    }),
  );

  // Billing/limits — present but minimal so the upgrade banner
  // doesn't crash.
  await page.route(/.*\/billing\/.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        plan_id: "plan-free",
        plan_name: "Free",
        status: "active",
        limits: {},
        usage: {},
      }),
    }),
  );

  await page.route(`${API_BASE}/developers/me`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "dev-1",
        name: "Test Dev",
        email: "test@example.com",
        github_connection: { github_username: "test", github_id: 1 },
        onboarding_completed: true,
        plan_id: "plan-free",
      }),
    }),
  );

  await page.route(`${API_BASE}/workspaces`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: "ws-1",
          name: "Test Workspace",
          slug: "test-ws",
          type: "internal",
          owner_id: "dev-1",
          plan_id: "plan-free",
          member_count: 1,
          team_count: 1,
          is_active: true,
        },
      ]),
    }),
  );

  // GET on a specific workspace.
  await page.route(/.*\/workspaces\/ws-1$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "ws-1",
        name: "Test Workspace",
        slug: "test-ws",
        type: "internal",
        owner_id: "dev-1",
        plan_id: "plan-free",
        is_active: true,
      }),
    }),
  );
}


test.describe("Automations — workflow Test button (UX-CHAT-bugfix)", () => {
  test("Test on unsaved /new lazy-creates the automation + fires the execute endpoint", async ({ page }) => {
    await setupAutomationsMocks(page);

    // Trace every request to /workspaces/ws-1 so debugging route
    // misses is easy. Strip the long API base for readability.
    const seenRequests: string[] = [];
    page.on("request", (req) => {
      const url = req.url();
      if (url.includes("/workspaces/ws-1")) {
        seenRequests.push(`${req.method()} ${url.replace(API_BASE, "")}`);
      }
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        console.log("PAGE ERROR:", msg.text());
      }
    });

    // Spies that record the auto-save chain.
    let createAutomationCalls = 0;
    let saveWorkflowCalls = 0;
    let patchAutomationCalls = 0;
    let executeCalls = 0;
    let lastExecuteBody: { dry_run?: boolean; record_id?: string } | null = null;

    // Auto-create endpoint — POST /workspaces/:ws/automations.
    await page.route(`${API_BASE}/workspaces/ws-1/automations`, async (route) => {
      if (route.request().method() === "POST") {
        createAutomationCalls += 1;
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            id: "automation-new-1",
            workspace_id: "ws-1",
            name: "New Automation",
            module: "crm",
            trigger_type: "record.created",
            is_active: false,
            actions: [],
            total_runs: 0,
          }),
        });
      } else {
        // GET /automations (list) — empty.
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      }
    });

    // Auto-save endpoint — PUT /workspaces/:ws/crm/automations/:id/workflow.
    await page.route(
      `${API_BASE}/workspaces/ws-1/crm/automations/automation-new-1/workflow`,
      async (route) => {
        if (route.request().method() === "PUT") {
          saveWorkflowCalls += 1;
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 }, version: 1 }),
          });
        } else {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 }, version: 1 }),
          });
        }
      },
    );

    // PATCH /workspaces/:ws/automations/:id — trigger_type sync.
    await page.route(
      `${API_BASE}/workspaces/ws-1/automations/automation-new-1`,
      async (route) => {
        if (route.request().method() === "PATCH") {
          patchAutomationCalls += 1;
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "automation-new-1",
            workspace_id: "ws-1",
            name: "New Automation",
            module: "crm",
            trigger_type: "record.created",
            is_active: false,
          }),
        });
      },
    );

    // The test endpoint itself — the whole point of this spec.
    await page.route(
      `${API_BASE}/workspaces/ws-1/crm/automations/automation-new-1/workflow/execute`,
      async (route) => {
        executeCalls += 1;
        try {
          const body = route.request().postDataJSON?.();
          lastExecuteBody = body ?? null;
        } catch {
          // ignore body parse errors
        }
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            execution_id: "exec-1",
            status: "completed",
            node_results: [],
            duration_ms: 42,
          }),
        });
      },
    );

    // Land on the gallery, then click "Start blank" to get to the
    // canvas. The `?blank=1` query param sometimes doesn't take on
    // the first render under Turbopack — driving the UI is more
    // robust and exercises the same path a user would.
    await page.goto("/automations/new");

    // Click the "Start blank" CTA. There are two — one in the header,
    // one in the grid; both fire the same handler. Use the first.
    await page
      .getByRole("button", { name: /Start blank|Open a blank canvas|Start from scratch/i })
      .first()
      .click();

    // Wait for the canvas toolbar to mount — Test button confirms.
    const testButton = page.getByRole("button", { name: /^Test$/ });
    await expect(testButton).toBeVisible({ timeout: 15000 });

    // Click Test → modal opens.
    await testButton.click();
    await expect(page.getByRole("heading", { name: "Test Workflow" })).toBeVisible();

    // Click Generate → fills the record ID input with a UUID.
    const recordIdInput = page.getByLabel("Record ID (optional)");
    await page.getByRole("button", { name: "Generate" }).click();
    await expect(recordIdInput).not.toHaveValue("");

    // Click Run Test inside the modal — there are two buttons labelled
    // similarly; target the primary "Run Test" inside the dialog.
    const runTestButton = page
      .getByRole("dialog")
      .getByRole("button", { name: /Run Test/i });
    await runTestButton.click();

    // Wait for the entire chain to fire. The execute endpoint is the
    // canonical "test actually ran" signal — assert THAT lands.
    try {
      await expect.poll(() => executeCalls, { timeout: 10000 }).toBe(1);
    } catch (e) {
      console.log("FAILED — requests to /workspaces/ws-1:");
      seenRequests.forEach((r) => console.log("  ", r));
      console.log("counters:", { createAutomationCalls, saveWorkflowCalls, patchAutomationCalls, executeCalls });
      throw e;
    }

    // Auto-save chain: create → save workflow → patch trigger.
    expect(createAutomationCalls).toBe(1);
    expect(saveWorkflowCalls).toBe(1);
    expect(patchAutomationCalls).toBe(1);

    // Body sanity: dry_run=true and the generated UUID flowed through.
    const body = lastExecuteBody as { dry_run?: boolean; record_id?: string } | null;
    expect(body?.dry_run).toBe(true);
    expect(body?.record_id).toBeTruthy();
    // Record id should look like a UUID (8-4-4-4-12 hex pattern).
    expect(body?.record_id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
    );
  });

  test("Test on a saved automation skips the auto-create + fires execute directly", async ({ page }) => {
    await setupAutomationsMocks(page);

    let createCalls = 0;
    let executeCalls = 0;

    // GET workflow for the existing automation.
    await page.route(
      `${API_BASE}/workspaces/ws-1/crm/automations/automation-existing/workflow`,
      async (route) => {
        if (route.request().method() === "GET") {
          await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
              nodes: [
                {
                  id: "trigger-1",
                  type: "trigger",
                  position: { x: 100, y: 100 },
                  data: { label: "When record created", trigger_type: "record.created" },
                },
              ],
              edges: [],
              viewport: { x: 0, y: 0, zoom: 1 },
              version: 3,
            }),
          });
        } else {
          await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
        }
      },
    );

    // GET the automation itself.
    await page.route(
      `${API_BASE}/workspaces/ws-1/automations/automation-existing`,
      async (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: "automation-existing",
            workspace_id: "ws-1",
            name: "Existing Automation",
            module: "crm",
            trigger_type: "record.created",
            is_active: true,
            actions: [],
            total_runs: 0,
          }),
        }),
    );

    // POST /workspaces/:ws/automations — should NOT fire on an
    // already-saved automation.
    await page.route(`${API_BASE}/workspaces/ws-1/automations`, async (route) => {
      if (route.request().method() === "POST") createCalls += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });

    await page.route(
      `${API_BASE}/workspaces/ws-1/crm/automations/automation-existing/workflow/execute`,
      async (route) => {
        executeCalls += 1;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            execution_id: "exec-2",
            status: "completed",
            node_results: [],
            duration_ms: 12,
          }),
        });
      },
    );

    await page.goto("/automations/automation-existing");

    const testButton = page.getByRole("button", { name: /^Test$/ });
    await expect(testButton).toBeVisible({ timeout: 15000 });

    await testButton.click();
    await expect(page.getByRole("heading", { name: "Test Workflow" })).toBeVisible();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /Run Test/i })
      .click();

    // Execute fires.
    await expect.poll(() => executeCalls, { timeout: 10000 }).toBe(1);
    // Auto-create did NOT fire — the automation already existed.
    expect(createCalls).toBe(0);
  });
});
