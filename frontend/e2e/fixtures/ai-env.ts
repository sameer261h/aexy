/**
 * AI E2E environment helper.
 *
 * Sits on top of `env.ts`. AI tests are ALWAYS live (no LLM mocking) —
 * mocked AI responses defeat the point of an AI E2E suite. So this
 * file:
 *
 *   1. Reads the same env vars as `env.ts`
 *      (E2E_REAL_BACKEND, AEXY_TEST_TOKEN, AEXY_TEST_WORKSPACE_ID).
 *   2. Adds LM Studio configuration (LMSTUDIO_BASE_URL, LMSTUDIO_MODEL)
 *      and a one-shot probe that skips the whole file when LM Studio
 *      is unreachable — same UX as the backend `tests/ai/` suite.
 *   3. Adds a `setupAiLiveAuth(page)` helper that primes the token +
 *      workspace in localStorage so the app boots into the workspace
 *      under test.
 *
 * Quick start:
 *   # 1. LM Studio running at :1234 with qwen/qwen3.5-9b loaded.
 *   # 2. Backend running at :8000, frontend at :3000.
 *   # 3. Generate a JWT:
 *   docker exec aexy-backend python scripts/generate_test_token.py --first
 *
 *   E2E_REAL_BACKEND=1 \
 *     AEXY_TEST_TOKEN=<jwt> \
 *     AEXY_TEST_WORKSPACE_ID=<uuid> \
 *     PLAYWRIGHT_BASE_URL=http://localhost:3000 \
 *     npx playwright test e2e/ai-*.spec.ts
 *
 * If LM Studio is down, every `ai-*.spec.ts` file no-ops with a single
 * skip line — same pattern as the backend suite.
 */

import type { APIRequestContext, Page } from "@playwright/test";

import {
  USE_REAL_BACKEND,
  REAL_BACKEND_TOKEN,
  REAL_BACKEND_WORKSPACE_ID,
} from "./env";

export {
  USE_REAL_BACKEND,
  REAL_BACKEND_TOKEN,
  REAL_BACKEND_WORKSPACE_ID,
};

/** Backend API base used by the frontend. */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

/** LM Studio config — matches what the backend `tests/ai/` suite uses. */
export const LMSTUDIO_BASE_URL =
  process.env.LMSTUDIO_BASE_URL || "http://localhost:1234/v1";
export const LMSTUDIO_MODEL =
  process.env.LMSTUDIO_MODEL || "qwen/qwen3.5-9b";
export const LMSTUDIO_PROBE_TIMEOUT_MS = Number(
  process.env.LMSTUDIO_PROBE_TIMEOUT_MS || 3000,
);

/**
 * Generous wait for any "user clicks → LLM responds" interaction.
 * Qwen-3.5-9b on a laptop GPU takes 5–30s for a typical analysis turn,
 * and an agent that runs a tool loop can take 60–120s. Keep the
 * default high so flakiness isn't masked as a UI bug.
 */
export const LLM_WAIT_MS = Number(process.env.AI_E2E_LLM_WAIT_MS || 180_000);

// ─── Probe (cached for the whole test session) ──────────────────────

type ProbeResult = { ok: boolean; reason: string };
let _probeCache: Promise<ProbeResult> | null = null;

async function _probeLmStudio(): Promise<ProbeResult> {
  // /v1/models is the same surface the provider uses — a probe pass
  // really means provider calls will work.
  const url = `${LMSTUDIO_BASE_URL.replace(/\/$/, "")}/models`;
  try {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), LMSTUDIO_PROBE_TIMEOUT_MS);
    const resp = await fetch(url, { signal: controller.signal });
    clearTimeout(t);
    if (!resp.ok) {
      return { ok: false, reason: `LM Studio returned HTTP ${resp.status} from ${url}` };
    }
    const body = (await resp.json()) as { data?: { id?: string }[] };
    const ids = (body.data ?? []).map((m) => m.id).filter(Boolean) as string[];
    if (!ids.includes(LMSTUDIO_MODEL)) {
      return {
        ok: false,
        reason:
          `Model "${LMSTUDIO_MODEL}" not present in LM Studio. Loaded: ` +
          `${JSON.stringify(ids)}. Load it or set LMSTUDIO_MODEL.`,
      };
    }
    return { ok: true, reason: "" };
  } catch (err) {
    return {
      ok: false,
      reason: `LM Studio probe failed at ${url}: ${String(err)}`,
    };
  }
}

export function probeLmStudio(): Promise<ProbeResult> {
  if (!_probeCache) _probeCache = _probeLmStudio();
  return _probeCache;
}

/**
 * The standard "should this AI spec run at all?" decision.
 *
 *   const ready = await aiLiveReady();
 *   test.skip(!ready.ok, ready.reason);
 *
 * `ok=false` if any of: live mode not enabled, token missing, workspace
 * missing, LM Studio unreachable, target model not loaded.
 */
export async function aiLiveReady(
  opts: { workspace?: boolean } = {},
): Promise<ProbeResult> {
  const base = await backendOnlyReady(opts);
  if (!base.ok) return base;
  const probe = await probeLmStudio();
  if (!probe.ok) return probe;
  return { ok: true, reason: "" };
}

/**
 * The "live backend, no LLM" variant for the automation E2E suite.
 *
 * Structural tests (canvas render, palette interaction, config-panel
 * fields, save round-trip) all hit the real backend but never call an
 * LLM provider — so the LM Studio probe is wasted overhead and would
 * skip the whole suite when LM Studio is down even though backend-only
 * tests would have passed. Use this in any ai-automation-*.spec.ts
 * that doesn't invoke generate-workflow / run_agent / etc.
 */
export async function backendOnlyReady(
  opts: { workspace?: boolean } = {},
): Promise<ProbeResult> {
  if (!USE_REAL_BACKEND) {
    return { ok: false, reason: "live-only — set E2E_REAL_BACKEND=1 to run" };
  }
  if (!REAL_BACKEND_TOKEN) {
    return {
      ok: false,
      reason:
        "AEXY_TEST_TOKEN is empty. Generate with: " +
        "docker exec aexy-backend python scripts/generate_test_token.py --first",
    };
  }
  if (opts.workspace !== false && !REAL_BACKEND_WORKSPACE_ID) {
    return {
      ok: false,
      reason:
        "AEXY_TEST_WORKSPACE_ID is empty. UI-driving tests need a workspace UUID.",
    };
  }
  return { ok: true, reason: "" };
}

// ─── Browser auth bootstrap ─────────────────────────────────────────

/**
 * Prime localStorage with the JWT + workspace ID AND the
 * middleware-visible `aexy_authed` presence cookie so the Next.js
 * app boots into the workspace under test. Must be called BEFORE
 * the first `page.goto(...)`.
 *
 * The cookie matters: `src/middleware.ts` redirects every protected
 * route to `/?next=...` if `aexy_authed=1` is missing — and the cookie
 * is normally set client-side by `useAuth`, AFTER mount. So without
 * the cookie being present at goto time, the very first navigation
 * to /automations/new (or any auth-required prefix) bounces through
 * the login page, dropping any query params we set.
 */
export async function setupAiLiveAuth(page: Page): Promise<void> {
  const token = REAL_BACKEND_TOKEN;
  const ws = REAL_BACKEND_WORKSPACE_ID;

  // Cookie on the test domain so the middleware sees us as
  // authenticated on the very first request. The init script below
  // only runs after navigation starts, which is too late for the
  // middleware that runs BEFORE the page is delivered. Playwright's
  // addCookies expects either `url` OR (`domain`+`path`), so go with
  // `url` and let Playwright derive domain/path from it.
  const baseUrl =
    process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
  await page.context().addCookies([
    {
      name: "aexy_authed",
      value: "1",
      url: baseUrl,
      sameSite: "Lax",
    },
  ]);

  await page.addInitScript(
    ([t, w]) => {
      try {
        localStorage.setItem("token", t);
        if (w) localStorage.setItem("current_workspace_id", w);
      } catch {
        // localStorage can be unavailable in some contexts — ignore.
      }
    },
    [token, ws],
  );
}

/**
 * Auth headers for backend-direct API calls
 * (Playwright's `request` fixture). Same shape every spec uses.
 */
export function authHeaders(): Record<string, string> {
  return {
    Authorization: `Bearer ${REAL_BACKEND_TOKEN}`,
    "Content-Type": "application/json",
  };
}

/**
 * Quick "is the backend even up?" — useful inside specs that want to
 * skip cleanly when the dev forgot to start docker-compose. Returns
 * true if `/api/v1/developers/me` answers 200 with our JWT.
 */
export async function backendReachable(
  request: APIRequestContext,
): Promise<boolean> {
  try {
    const r = await request.get(`${API_BASE}/developers/me`, {
      headers: authHeaders(),
      timeout: 5000,
    });
    return r.ok();
  } catch {
    return false;
  }
}
