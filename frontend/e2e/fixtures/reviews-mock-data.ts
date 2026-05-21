/**
 * Shared mock setup + data for the reviews e2e specs.
 *
 * Every reviews route is gated by workspace membership + (for admin
 * routes) workspace admin role. The frontend reads the current
 * developer + workspace at app boot via `/developers/me` and
 * `/workspaces`, and the AppShell then probes app-access at
 * `/workspaces/:ws/app-access/members/:dev/effective`. These three
 * endpoints are the prereq for ANY protected route to render, so
 * we mock them once here.
 *
 * Each spec adds its own per-test routes on top — cycle endpoints,
 * peer-request endpoints, etc. — and counts calls via Page-level
 * spies. The shared fixture only handles the boot path + a few
 * "is the app shell happy?" endpoints (notifications, members,
 * billing).
 */

import type { Page } from "@playwright/test";

import {
  USE_REAL_BACKEND,
  REAL_BACKEND_TOKEN,
  REAL_BACKEND_WORKSPACE_ID,
  assertLiveModeReady,
} from "./env";

export const API_BASE = "http://localhost:8000/api/v1";

// In live mode the spec talks to a real backend, so the developer +
// workspace IDs must come from the caller's env (the JWT carries the
// developer id; the workspace UUID is selected explicitly).
export const DEV = USE_REAL_BACKEND
  ? {
      // The real developer id is encoded in the JWT's `sub` claim;
      // we decode it lazily so specs that don't need it don't pay
      // the parse cost.
      id: decodeJwtSub(REAL_BACKEND_TOKEN) || "live-dev",
      name: "Live Developer",
      email: "live@example.com",
    }
  : {
      id: "62bb4730-57a3-4015-bbda-217d727b95b9",
      name: "Test Developer",
      email: "test@example.com",
    };

export const WORKSPACE = USE_REAL_BACKEND
  ? {
      id: REAL_BACKEND_WORKSPACE_ID,
      name: "Live Workspace",
      slug: "live-ws",
      type: "internal" as const,
      owner_id: DEV.id,
      plan_id: "plan-free",
      member_count: 1,
      team_count: 1,
      is_active: true,
    }
  : {
      id: "f67c7124-38e4-4a4b-8e89-da56e413ef13",
      name: "Test Workspace",
      slug: "test-ws",
      type: "internal" as const,
      owner_id: DEV.id,
      plan_id: "plan-free",
      member_count: 5,
      team_count: 1,
      is_active: true,
    };

function decodeJwtSub(jwt: string): string {
  if (!jwt) return "";
  try {
    const payload = jwt.split(".")[1];
    if (!payload) return "";
    // base64url → base64
    const b64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const json = Buffer.from(b64, "base64").toString("utf-8");
    return JSON.parse(json).sub ?? "";
  } catch {
    return "";
  }
}

// Roles the auth helpers care about. Specs pass one of these into
// `setupReviewsMocks({ role })` so the effective-access mock returns
// the right answer for `is_admin`.
export type Role = "admin" | "member";

interface SetupOptions {
  role?: Role;
}

export async function setupReviewsMocks(page: Page, opts: SetupOptions = {}) {
  const role: Role = opts.role ?? "member";

  // Live mode: skip every `page.route` mock and seed real auth so
  // the page talks to a real backend at NEXT_PUBLIC_API_URL. The
  // role param is ignored — the real backend decides what the
  // logged-in developer can see based on their workspace
  // membership.
  // The middleware redirects auth-required routes to `/` unless the
  // `aexy_authed=1` cookie is present. The cookie is normally
  // mirrored from localStorage by useAuth on mount — too late for the
  // first SSR pass. Seed it directly so the test's first navigation
  // doesn't bounce through the landing page.
  const baseURL =
    process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3000";
  await page.context().addCookies([
    {
      name: "aexy_authed",
      value: "1",
      url: baseURL,
    },
  ]);

  if (USE_REAL_BACKEND) {
    // Token is the hard requirement. Workspace id is only needed by
    // tests that navigate to a workspace-scoped page; those guard
    // themselves with `test.skip(!REAL_BACKEND_WORKSPACE_ID, ...)`.
    assertLiveModeReady({ workspace: false });
    await page.addInitScript(
      ({ token, workspaceId }) => {
        localStorage.setItem("token", token);
        if (workspaceId)
          localStorage.setItem("current_workspace_id", workspaceId);
      },
      { token: REAL_BACKEND_TOKEN, workspaceId: REAL_BACKEND_WORKSPACE_ID },
    );
    return;
  }

  // Prime localStorage BEFORE any navigation so the very first
  // render sees an authed state. The current_workspace_id key is
  // what useWorkspace reads to skip the workspace picker.
  await page.addInitScript(
    ({ token, workspaceId }) => {
      localStorage.setItem("token", token);
      localStorage.setItem("current_workspace_id", workspaceId);
    },
    { token: "fake-test-token", workspaceId: WORKSPACE.id },
  );

  // Catch-all returns an empty array. Many list hooks crash on a
  // non-iterable response; this keeps the app shell happy until a
  // spec overrides with a more specific shape. Playwright matches
  // routes in REVERSE registration order, so registering this FIRST
  // makes it the LAST candidate considered.
  await page.route(`${API_BASE}/**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    }),
  );

  // Object-shaped overrides. Hooks that destructure these fields
  // throw on the bare-array catch-all.
  await page.route(`${API_BASE}/notifications/poll**`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ notifications: [], unread_count: 0 }),
    }),
  );
  // useNotifications.list expects { notifications, unread_count, has_next }.
  await page.route(/.*\/notifications(\?.*)?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        notifications: [],
        unread_count: 0,
        has_next: false,
      }),
    }),
  );
  await page.route(/.*\/notifications\/unread-count.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ count: 0 }),
    }),
  );

  // ReviewDigestCard reads `data.snapshots.find(...)` so the catch-all
  // bare-array crashes it. Return the expected object shape.
  await page.route(/.*\/code-insights\/snapshots.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ snapshots: [] }),
    }),
  );

  await page.route(`${API_BASE}/developers/me`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: DEV.id,
        name: DEV.name,
        email: DEV.email,
        avatar_url: null,
        github_connection: { github_username: "testdev", github_id: 123 },
        onboarding_completed: true,
        plan_id: "plan-free",
      }),
    }),
  );

  await page.route(`${API_BASE}/workspaces`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([WORKSPACE]),
    }),
  );
  await page.route(new RegExp(`${API_BASE}/workspaces/${WORKSPACE.id}$`), (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(WORKSPACE),
    }),
  );

  // Effective-access keyed by app id. Reviews routes need at minimum
  // "reviews" enabled; we flip everything on so the sidebar / nav
  // don't gate any link. is_admin drives admin-only UI bits like the
  // cycle CRUD buttons.
  await page.route(
    new RegExp(`/workspaces/${WORKSPACE.id}/app-access/members/.+/effective`),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          apps: Object.fromEntries(
            [
              "reviews",
              "agents",
              "automations",
              "dashboard",
              "crm",
              "docs",
              "tickets",
              "email_marketing",
              "hiring",
              "sprints",
              "forms",
              "tables",
              "uptime",
              "tracking",
              "compliance",
              "gtm",
              "analytics",
              "insights",
              "reports",
              "learning",
              "booking",
              "onboarding",
              "notifications",
            ].map((id) => [id, { enabled: true, role }]),
          ),
          applied_template_id: null,
          applied_template_name: null,
          has_custom_overrides: false,
          is_admin: role === "admin",
        }),
      }),
  );

  // Members + spaces + drive — empty, the reviews pages don't read
  // them but the sidebar may.
  await page.route(new RegExp(`/workspaces/${WORKSPACE.id}/members.*`), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(new RegExp(`/workspaces/${WORKSPACE.id}/spaces.*`), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(new RegExp(`/workspaces/${WORKSPACE.id}/documents/.*`), (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );

  // Billing — minimal so UpgradeBanner doesn't blow up.
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
}


// Some pages call /reviews/contributions/summary on mount; provide
// a default empty response that specs can override. No-op in live
// mode — the real backend is the source of truth.
export async function mockEmptyContributionsSummary(page: Page) {
  if (USE_REAL_BACKEND) return;
  await page.route(/.*\/reviews\/contributions\/summary.*/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        developer_id: DEV.id,
        period_start: "2025-01-01",
        period_end: "2025-03-31",
        metrics: {
          commits_count: 0,
          prs_opened: 0,
          prs_merged: 0,
          prs_closed: 0,
          reviews_given: 0,
          reviews_approved: 0,
          reviews_changes_requested: 0,
          reviews_commented: 0,
          lines_added: 0,
          lines_deleted: 0,
          languages: {},
          skills_demonstrated: [],
        },
        highlights: [],
        ai_insights: null,
        generated_at: "2025-01-01T00:00:00Z",
      }),
    }),
  );
}


/** Helpers spec files use to spy on a single endpoint. Returns a
 *  counter ref + a JSON-body recorder. The mock fulfills with the
 *  caller's `respond` callback so specs control the wire shape.
 *
 *  In live mode this becomes a passive listener: no `page.route`
 *  interception, the request goes through to the real backend, but
 *  we still increment `calls` and capture `lastBody` via the
 *  `page.on("request")` event so spec assertions like
 *  `expect.poll(() => spy.calls).toBe(1)` keep working.
 *  Spec assertions that check the SHAPE of the request body still
 *  pass — those are tests of the frontend, not the mock. Spec
 *  assertions that depend on a SPECIFIC mocked response (e.g.
 *  "show this error toast for a 403") should guard with
 *  `test.skip(USE_REAL_BACKEND, ...)` since the real backend will
 *  return its own response. */
export function makeSpiedRoute<TBody = unknown>(
  page: Page,
  pattern: string | RegExp,
  respond: (body: TBody | null) => { status?: number; body: unknown },
  match: (method: string) => boolean = () => true,
) {
  const state = { calls: 0, lastBody: null as TBody | null };

  if (USE_REAL_BACKEND) {
    page.on("request", (req) => {
      const url = req.url();
      const matchesPattern =
        typeof pattern === "string"
          ? url.includes(pattern)
          : pattern.test(url);
      if (!matchesPattern) return;
      if (!match(req.method())) return;
      state.calls += 1;
      try {
        state.lastBody = (req.postDataJSON?.() ?? null) as TBody | null;
      } catch {
        state.lastBody = null;
      }
    });
    return state;
  }

  page.route(pattern, async (route) => {
    if (!match(route.request().method())) {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      });
    }
    state.calls += 1;
    try {
      state.lastBody = (route.request().postDataJSON?.() ?? null) as TBody | null;
    } catch {
      state.lastBody = null;
    }
    const { status, body } = respond(state.lastBody);
    await route.fulfill({
      status: status ?? 200,
      contentType: "application/json",
      body: typeof body === "string" ? body : JSON.stringify(body),
    });
  });
  return state;
}
