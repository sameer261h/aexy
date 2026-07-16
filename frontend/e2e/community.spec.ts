/**
 * Public community forum — end-to-end (UI) test.
 *
 * Drives the live stack (real frontend + backend). Because it needs an enabled
 * community with a web-public channel/topic — state that can't be created via
 * the public API — it is env-gated like the AI specs: provide the seed config
 * and it runs, otherwise the whole file skips.
 *
 * Seed with backend/scripts (see PUBLIC_COMMUNITY_CHAT_PLAN.md) and pass:
 *   COMMUNITY_SLUG=<slug> \
 *   COMMUNITY_TOPIC_PARAM=<topicSlug>-<shortId> \
 *   COMMUNITY_POSTER_TOKEN=<jwt for any Developer> \
 *   PLAYWRIGHT_BASE_URL=http://localhost:3000 \
 *   API_BASE_URL=http://localhost:8000/api/v1 \
 *   npx playwright test e2e/community.spec.ts
 */
import { test, expect } from "@playwright/test";

const BASE = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
const API = process.env.API_BASE_URL || "http://localhost:8000/api/v1";
const CS = process.env.COMMUNITY_SLUG;
const TP = process.env.COMMUNITY_TOPIC_PARAM;
const TOKEN = process.env.COMMUNITY_POSTER_TOKEN;
const CHANNEL = process.env.COMMUNITY_CHANNEL_SLUG || "general";

const configured = Boolean(CS && TP && TOKEN);
test.skip(!configured, "Set COMMUNITY_SLUG / COMMUNITY_TOPIC_PARAM / COMMUNITY_POSTER_TOKEN to run");

test.describe("public community forum", () => {
  const topicUrl = `${BASE}/community/${CS}/${CHANNEL}/${TP}`;

  test("anonymous can read; signed-in participant can post", async ({ page }) => {
    // 1. Anonymous: content renders, read-only CTA, no composer.
    await page.goto(topicUrl, { waitUntil: "networkidle" });
    await expect(page.locator("h1")).toBeVisible();
    await expect(page.getByTestId("community-signin-cta")).toHaveCount(1);
    await expect(page.getByTestId("community-reply-form")).toHaveCount(0);

    // 2. Sign in (inject token like the app does after OAuth) → composer appears.
    await page.evaluate((t) => localStorage.setItem("token", t), TOKEN!);
    await page.reload({ waitUntil: "networkidle" });
    await expect(page.getByTestId("community-reply-form")).toBeVisible();
    await expect(page.getByTestId("community-signin-cta")).toHaveCount(0);

    // 3. Post a reply through the UI.
    const replyText = `UI e2e reply ${Date.now()}`;
    await page.getByTestId("community-reply-input").fill(replyText);
    await page.getByTestId("community-reply-submit").click();
    await expect(page.getByTestId("community-reply-notice")).toBeVisible();

    // 4. Persistence via the backend API (the SSR page is ISR-cached ~5 min).
    const res = await page.request.get(
      `${API}/public/community/${CS}/channels/${CHANNEL}/topics/${TP}`,
    );
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    const contents = (body.messages as Array<{ content: string }>).map((m) => m.content);
    expect(contents).toContain(replyText);
  });

  test("anonymous reply is rejected by the API (401)", async ({ request }) => {
    const res = await request.post(
      `${API}/public/community/${CS}/channels/${CHANNEL}/topics/${TP}/replies`,
      { data: { content: "should fail" } },
    );
    expect(res.status()).toBe(401);
  });
});
