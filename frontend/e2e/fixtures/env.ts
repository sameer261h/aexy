/**
 * E2E environment flags.
 *
 * Two run modes:
 *
 * 1. **Mock mode** (default) — `page.route(...)` intercepts every backend
 *    call, fulfilled with stubbed responses. Fast, deterministic, no
 *    network or auth needed. This is what most specs assume.
 *
 * 2. **Live mode** — `E2E_REAL_BACKEND=1`. No mocks installed; the
 *    frontend talks to a real backend at `NEXT_PUBLIC_API_URL`. The
 *    test runner needs a real JWT (`AEXY_TEST_TOKEN`) and the workspace
 *    UUID to drive (`AEXY_TEST_WORKSPACE_ID`). Specs that depend on
 *    spied `makeSpiedRoute` payload assertions are skipped — only the
 *    "does the page load + the user action complete" portion runs.
 *
 *    Generate a token: `docker exec aexy-backend python scripts/generate_test_token.py --first`
 *
 *    Run: `E2E_REAL_BACKEND=1 AEXY_TEST_TOKEN=<jwt> AEXY_TEST_WORKSPACE_ID=<uuid> \
 *           PLAYWRIGHT_BASE_URL=http://localhost:3000 \
 *           npx playwright test reviews-self-review.spec.ts`
 *
 * The flag is read once at import time; flip it via env vars, not at
 * runtime.
 */

export const USE_REAL_BACKEND = process.env.E2E_REAL_BACKEND === "1";

/**
 * In live mode, the spec MUST set these or it'll fail with a 401 on
 * the first request. We surface a precise error rather than letting
 * the user puzzle over a confusing 401 trace.
 */
export const REAL_BACKEND_TOKEN = process.env.AEXY_TEST_TOKEN ?? "";
export const REAL_BACKEND_WORKSPACE_ID =
  process.env.AEXY_TEST_WORKSPACE_ID ?? "";

/**
 * Token is required for ANY live-mode test. Workspace ID is only
 * required for tests that navigate the UI (so the page-shell knows
 * which workspace to bootstrap into). Contract tests that POST
 * directly with the JWT need only the token.
 */
export function assertLiveModeReady(opts: { workspace?: boolean } = {}): void {
  if (!USE_REAL_BACKEND) return;
  const missing: string[] = [];
  if (!REAL_BACKEND_TOKEN) missing.push("AEXY_TEST_TOKEN");
  if (opts.workspace !== false && !REAL_BACKEND_WORKSPACE_ID) {
    missing.push("AEXY_TEST_WORKSPACE_ID");
  }
  if (missing.length > 0) {
    throw new Error(
      `E2E_REAL_BACKEND=1 but missing env vars: ${missing.join(", ")}. ` +
        `Generate a token with: ` +
        `docker exec aexy-backend python scripts/generate_test_token.py --first`,
    );
  }
}
