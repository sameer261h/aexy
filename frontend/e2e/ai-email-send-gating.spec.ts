/**
 * E2E: E2.6 campaign send-gating (live backend, no LLM).
 *
 * The campaign "Send Now" button must be disabled until the workspace has a
 * verified sending domain. Asserted against the *actual* domain state so the
 * test is deterministic regardless of what the workspace has configured.
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

const SENDABLE = ["verified", "active", "warming"];

test.describe("Email campaign send-gating (live)", () => {
  test("Send Now is disabled iff the workspace has no verified sending domain", async ({
    page,
    request,
  }) => {
    const ready = await backendOnlyReady();
    test.skip(!ready.ok, ready.reason);
    await setupAiLiveAuth(page);

    // Actual domain state → expected button state.
    const domResp = await request.get(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/email-infrastructure/domains`,
      { headers: authHeaders() },
    );
    const domains = await domResp.json();
    const list = Array.isArray(domains) ? domains : domains.domains ?? [];
    const hasVerifiedSender = list.some((d: { status: string }) => SENDABLE.includes(d.status));

    // Seed a draft campaign so the "Send Now" button renders.
    const created = await request.post(
      `${API_BASE}/workspaces/${REAL_BACKEND_WORKSPACE_ID}/email-marketing/campaigns`,
      {
        headers: authHeaders(),
        data: { name: `E2E gate ${Date.now()}`, from_name: "Sender", from_email: "sender@example.com" },
      },
    );
    expect(created.ok(), `create campaign failed: ${created.status()}`).toBeTruthy();
    const campaignId = (await created.json()).id;

    await page.goto(`/email-marketing/campaigns/${campaignId}`, { waitUntil: "networkidle" });

    const sendBtn = page.getByRole("button", { name: /Send Now/i });
    await expect(sendBtn).toBeVisible({ timeout: 15_000 });

    if (hasVerifiedSender) {
      await expect(sendBtn).toBeEnabled();
    } else {
      await expect(sendBtn).toBeDisabled();
    }
  });
});
