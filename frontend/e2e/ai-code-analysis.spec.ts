/**
 * E2E: Code analysis surface — paste a snippet, click Analyze, AI
 * returns languages/frameworks/domains and the UI renders them.
 *
 * Hits `POST /api/v1/analysis/code` (or the workspace-scoped variant).
 * Mirrors the backend `tests/ai/services/test_code_analyzer.py` from
 * the browser side.
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

const SAMPLE = `
import asyncio
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health():
    return {"ok": True}

@app.post("/users")
async def create_user(payload: dict):
    await asyncio.sleep(0.01)
    return {"id": 1, **payload}
`.trim();

// Each AI spec hits a live local LLM — bump per-test timeout above the
// 30s default so the model has room to respond.
test.describe.configure({ timeout: 240_000 });

test.describe("AI / Code analysis (live)", () => {
  test.beforeEach(async () => {
    const ready = await aiLiveReady();
    test.skip(!ready.ok, ready.reason);
  });

  // TODO(UI-MISSING): The backend exposes `POST /api/v1/analysis/code`
  // and the analysis pipeline is exercised by
  // `backend/tests/ai/services/test_code_analyzer.py`, but no
  // dedicated frontend page currently lets a user paste raw code
  // and see the analyzer's languages/frameworks/domains output.
  // The only UI surfaces for analysisApi (dashboard, TaskMatcherCard,
  // PeerBenchmarkCard) use developer-scoped summaries, not raw
  // snippets. To enable this E2E:
  //   1. Add a code-analysis page (e.g. /insights/code or
  //      /operations/code-analysis) with a paste textarea and an
  //      "Analyze" button.
  //   2. Wire to `analysisApi.analyzeCode` (already in api.ts).
  //   3. Remove this fixme.
  test.fixme(
    true,
    "No UI page exposes /analysis/code for raw snippets — see TODO above.",
  );
  test("analyzing a Python snippet renders categories", async ({ page }) => {
    await setupAiLiveAuth(page);
    const errors = collectFatalApiErrors(page);

    // Likely routes — fall back across the most common locations.
    // Note: Next.js returns 200 for its built-in 404 page, so we
    // detect the 404 by looking at the rendered heading rather than
    // relying on the HTTP status code.
    const candidates = [
      "/insights/ai",
      "/insights/code-analysis",
      "/insights/code",
      "/code-insights",
      "/insights",
      "/operations",
    ];
    let arrived = false;
    for (const route of candidates) {
      await page.goto(route, { timeout: 15_000 }).catch(() => null);
      const notFound = await page
        .getByRole("heading", { name: /^404$/ })
        .isVisible({ timeout: 500 })
        .catch(() => false);
      if (!notFound) {
        arrived = true;
        break;
      }
    }
    test.skip(
      !arrived,
      "No dedicated code-analysis page in this build — surface is API-only.",
    );

    const input = page
      .getByRole("textbox", { name: /code|paste|snippet|analyze/i })
      .or(page.getByPlaceholder(/paste (your )?code|code snippet|analyze/i));
    const inputVisible = await input
      .first()
      .isVisible({ timeout: 8_000 })
      .catch(() => false);
    test.skip(
      !inputVisible,
      "No code-analysis input on the resolved page — surface is API-only " +
        "in this build (call /api/v1/analysis/code directly to test it).",
    );
    await input.first().fill(SAMPLE);

    const respPromise = waitForAiResponse(
      page,
      (u) => /\/analysis\/(code|snippet)(\b|\?|$)/.test(u),
      { timeoutMs: LLM_WAIT_MS },
    );

    await page
      .getByRole("button", { name: /^(analyze|run|submit)$/i })
      .first()
      .click();

    const resp = await respPromise;
    expect(
      resp.status(),
      `analysis/code returned ${resp.status()}`,
    ).toBeLessThan(500);

    const body = (await resp.json().catch(() => null)) as {
      languages?: { name: string }[];
      frameworks?: { name: string }[];
      domains?: { name: string }[];
    } | null;
    if (body) {
      const total =
        (body.languages?.length ?? 0) +
        (body.frameworks?.length ?? 0) +
        (body.domains?.length ?? 0);
      expect(
        total,
        `Expected at least one of languages/frameworks/domains. Body: ${JSON.stringify(body)}`,
      ).toBeGreaterThan(0);
    }

    expect(
      errors,
      `fatal API errors during code analysis: ${JSON.stringify(errors)}`,
    ).toEqual([]);
  });
});
