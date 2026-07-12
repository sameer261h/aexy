/**
 * E2E: CRM sidebar navigation shell.
 *
 * Verifies the CRM section of the app sidebar renders its expected
 * sub-items and that clicking each one navigates to the right route
 * and highlights it as active. Mocked backend (no live services) —
 * mirrors the route-interception pattern used by e2e/leave.spec.ts.
 */

import { test, expect, Page } from "@playwright/test";
import {
  mockWorkspace,
  mockUser,
  mockEffectiveAccess,
  mockDashboardPreferences,
  CRM_NAV_ITEMS,
} from "../src/test/crm/navigation/fixtures";

const API_BASE = "http://localhost:8000/api/v1";

async function setupCrmNavMocks(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("token", "fake-test-token");
    localStorage.setItem("current_workspace_id", "ws-1");
  });

  // Catch-all FIRST (checked LAST by Playwright)
  await page.route(`${API_BASE}/**`, (route) => {
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
  });

  await page.route(`${API_BASE}/workspaces`, (route) => {
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([mockWorkspace]) });
  });

  await page.route(`${API_BASE}/workspaces/**`, (route) => {
    const url = route.request().url();

    if (url.includes("/app-access/")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(mockEffectiveAccess) });
    }
    if (url.includes("/documents/")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    }
    if (url.includes("/ws-1/spaces")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    }
    if (url.includes("/members")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    }
    if (url.includes("/invites")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    }
    if (url.includes("/task-statuses")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    }
    if (url.includes("/apps")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    }
    if (url.includes("/billing")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ plan: "pro", status: "active" }) });
    }
    if (url.includes("/teams")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    }
    if (url.includes("/notifications")) {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([]) });
    }

    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(mockWorkspace) });
  });

  await page.route(`${API_BASE}/developers/me`, (route) => {
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(mockUser) });
  });

  await page.route(`${API_BASE}/dashboard/preferences`, (route) => {
    if (route.request().method() === "GET") {
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(mockDashboardPreferences) });
    } else {
      route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
    }
  });
}

// The CRM sub-items live in a collapsed submenu until the parent "CRM"
// row's chevron is toggled — Sidebar.tsx keeps `expandedItems` state
// per-href and does not auto-expand based on the active route.
async function expandCrmSection(page: Page) {
  const crmParentLink = page.getByRole("link", { name: "CRM", exact: true });
  await expect(crmParentLink).toBeVisible();
  const toggleButton = crmParentLink.locator("xpath=following-sibling::button[1]");
  await toggleButton.click();
}

test.describe("CRM sidebar navigation shell", () => {
  test.beforeEach(async ({ page }) => {
    await setupCrmNavMocks(page);
    await page.goto("/crm");
    await expandCrmSection(page);
  });

  test("renders every expected CRM sub-item as a link to its route", async ({ page }) => {
    for (const item of CRM_NAV_ITEMS) {
      const link = page.locator(`a[href="${item.href}"]`, { hasText: item.label });
      await expect(link.first()).toBeVisible();
    }
  });

  test("clicking a CRM sub-item navigates to its route", async ({ page }) => {
    const inbox = CRM_NAV_ITEMS.find((i) => i.label === "Inbox")!;
    await page.locator(`a[href="${inbox.href}"]`, { hasText: inbox.label }).first().click();
    await expect(page).toHaveURL(new RegExp(`${inbox.href}$`));
  });

  test("marks the current CRM route's sidebar link as active", async ({ page }) => {
    const activities = CRM_NAV_ITEMS.find((i) => i.label === "Activities")!;
    await page.goto(activities.href);
    await expandCrmSection(page);

    const link = page.locator(`a[href="${activities.href}"]`, { hasText: activities.label }).first();
    const activeContainer = link.locator("xpath=parent::div");
    await expect(activeContainer).toHaveClass(/bg-accent/);
  });
});
