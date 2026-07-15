/**
 * E2E: CRM activity feed (E3) — live backend, no LLM.
 *
 * Guards the E3 fixes at the UI layer:
 *   - the feed loads at all (it used to 500 on a reserved-name bug),
 *   - the "Created" tab actually filters to record.created activities
 *     (the tab key `record_created` vs the dotted stored type),
 *   - the actor renders as a real name, not the generic "User" fallback,
 *   - the "Automations" tab is wired (E3.5).
 */

import { expect, test } from "@playwright/test";

import {
  API_BASE,
  REAL_BACKEND_WORKSPACE_ID,
  authHeaders,
  backendOnlyReady,
  setupAiLiveAuth,
} from "./fixtures/ai-env";

test.describe.configure({ timeout: 120_000 });

test.describe("CRM activity feed (live)", () => {
  let devName = "";

  test.beforeEach(async ({ page, request }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);

    // Who is the authenticated developer? Their name must show as the actor.
    const me = await request.get(`${API_BASE}/developers/me`, { headers: authHeaders() });
    devName = (await me.json()).name;
    expect(devName, "test developer needs a name").toBeTruthy();

    // Seed a record → generates a `record.created` activity attributed to devName.
    const objsResp = await request.get(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/objects`,
      { headers: authHeaders() },
    );
    const objs = await objsResp.json();
    const obj = (Array.isArray(objs) ? objs : objs.items ?? [])[0];
    await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/crm/objects/${obj.id}/records`,
      { headers: authHeaders(), data: { values: { name: "E2E Activity Seed", email: "e2e-seed@example.com" } } },
    );
  });

  test("Created tab filters to created activities with a real actor name", async ({ page }) => {
    await page.goto("/crm/activities", { waitUntil: "networkidle" });

    // Feed loaded (regression: it used to 500).
    await expect(page.getByText(/\d+ activit(y|ies)/)).toBeVisible({ timeout: 15_000 });

    // Filter to Created — the count line annotates the active filter.
    await page.getByRole("button", { name: "Created" }).click();
    await expect(page.getByText(/\(Created\)/)).toBeVisible({ timeout: 10_000 });

    // Actor resolves to the developer's name, not the generic "User".
    await expect(page.getByText(devName).first()).toBeVisible({ timeout: 10_000 });
  });

  test("Automations tab is available (E3.5 wiring)", async ({ page }) => {
    await page.goto("/crm/activities", { waitUntil: "networkidle" });
    await expect(
      page.getByRole("button", { name: "Automations" }),
    ).toBeVisible({ timeout: 15_000 });
  });
});
